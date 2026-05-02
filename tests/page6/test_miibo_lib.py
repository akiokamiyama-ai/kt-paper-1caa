"""Unit tests for scripts/lib/miibo.py.

Run::

    python3 -m tests.page6.test_miibo_lib

External HTTP is fully mocked via monkey-patching ``urllib.request.urlopen``
at the miibo module level. No real API call ever fires.
"""

from __future__ import annotations

import io
import json
import os
import sys
import urllib.error
from contextlib import contextmanager

from scripts.lib import miibo

PASS = 0
FAIL = 0


def _check(label: str, condition: bool, detail: str = "") -> bool:
    global PASS, FAIL
    sym = "✓" if condition else "✗"
    line = f"  {sym} {label}"
    if detail:
        line += f"  ({detail})"
    print(line)
    if condition:
        PASS += 1
    else:
        FAIL += 1
    return condition


# ---------------------------------------------------------------------------
# Mock HTTP infrastructure
# ---------------------------------------------------------------------------

class _FakeResponse:
    def __init__(self, body: bytes, status: int = 200):
        self._body = body
        self._status = status

    def read(self):
        return self._body

    def getcode(self):
        return self._status

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@contextmanager
def _mock_urlopen(responses):
    """Replace urllib.request.urlopen.

    ``responses`` is a list of either:
    - bytes (200 OK with that body)
    - (status_code, body_bytes) tuples
    - urllib.error.HTTPError instance to raise
    - urllib.error.URLError instance to raise
    Consumed in order.
    """
    import urllib.request as ur
    original = ur.urlopen
    calls = []

    def fake_urlopen(req, timeout=None):
        idx = min(len(calls), len(responses) - 1)
        item = responses[idx]
        # Capture the request body
        body = req.data
        try:
            parsed_body = json.loads(body) if body else {}
        except json.JSONDecodeError:
            parsed_body = {"_raw": body}
        calls.append({"url": req.full_url, "body": parsed_body, "timeout": timeout})
        if isinstance(item, Exception):
            raise item
        if isinstance(item, tuple):
            status, body_b = item
            if status >= 400:
                err = urllib.error.HTTPError(
                    req.full_url, status, "fake", {},
                    io.BytesIO(body_b),
                )
                raise err
            return _FakeResponse(body_b, status=status)
        return _FakeResponse(item, status=200)

    ur.urlopen = fake_urlopen
    try:
        yield calls
    finally:
        ur.urlopen = original


# ---------------------------------------------------------------------------
# (a) Credentials
# ---------------------------------------------------------------------------

def test_credentials_missing_key_raises():
    saved = os.environ.pop(miibo.MIIBO_API_KEY_ENV, None)
    try:
        raised = False
        try:
            miibo.get_miibo_credentials()
        except RuntimeError:
            raised = True
        _check("a1 missing MIIBO_API_KEY → RuntimeError", raised)
    finally:
        if saved is not None:
            os.environ[miibo.MIIBO_API_KEY_ENV] = saved


def test_credentials_missing_agent_raises():
    saved = os.environ.pop(miibo.MIIBO_AGENT_ID_ENV, None)
    try:
        raised = False
        try:
            miibo.get_miibo_credentials()
        except RuntimeError:
            raised = True
        _check("a2 missing MIIBO_AGENT_ID → RuntimeError", raised)
    finally:
        if saved is not None:
            os.environ[miibo.MIIBO_AGENT_ID_ENV] = saved


def test_credentials_present_returns_tuple():
    if not (os.environ.get(miibo.MIIBO_API_KEY_ENV)
            and os.environ.get(miibo.MIIBO_AGENT_ID_ENV)):
        _check("a3 SKIP: env vars not set in this shell", True,
               "test environment-dependent")
        return
    key, agent = miibo.get_miibo_credentials()
    ok = isinstance(key, str) and isinstance(agent, str) and key and agent
    _check("a3 env present → returns (key, agent_id) tuple", ok)


# ---------------------------------------------------------------------------
# (b) redact_miibo_key
# ---------------------------------------------------------------------------

def test_redact_replaces_literal_key():
    key = "abc123XYZ"
    text = f"error: api_key={key} failed"
    out = miibo.redact_miibo_key(text, key)
    ok = key not in out and "[REDACTED_MIIBO_KEY]" in out
    _check("b1 redact replaces literal key value", ok, f"got {out!r}")


def test_redact_empty_inputs_passthrough():
    _check("b2 None text passes through",
           miibo.redact_miibo_key(None, "key") is None)
    _check("b3 empty key returns text unchanged",
           miibo.redact_miibo_key("hello", "") == "hello")


def test_redact_no_match_unchanged():
    text = "no key in this text"
    _check("b4 no occurrence → unchanged",
           miibo.redact_miibo_key(text, "abc123") == text)


# ---------------------------------------------------------------------------
# (c) call_ai_kamiyama happy path + fallback
# ---------------------------------------------------------------------------

def _good_response_json(utterance="今朝の一筆") -> bytes:
    return json.dumps({
        "bestResponse": {"utterance": utterance, "score": 1.0},
    }, ensure_ascii=False).encode("utf-8")


def test_call_happy_path():
    body = _good_response_json("素敵な発見ですね。")
    with _mock_urlopen([body]) as calls:
        resp = miibo.call_ai_kamiyama(
            "test utterance",
            api_key="fakekey", agent_id="fakeagent",
        )
    ok = (
        resp.utterance_response == "素敵な発見ですね。"
        and resp.elapsed_ms >= 0
        and len(calls) == 1
        and calls[0]["body"]["utterance"] == "test utterance"
        and calls[0]["body"]["api_key"] == "fakekey"
        and calls[0]["body"]["agent_id"] == "fakeagent"
    )
    _check("c1 happy path: utterance + body sent + parsed", ok,
           f"resp={resp.utterance_response[:30]!r}, calls={len(calls)}")


def test_call_4xx_no_retry():
    """4xx は即 fail（auth error は retry しても回復しない）"""
    err_body = b'{"error": "invalid api_key"}'
    with _mock_urlopen([(401, err_body)]) as calls:
        raised = False
        try:
            miibo.call_ai_kamiyama(
                "x", api_key="bad", agent_id="bad", max_retries=2,
            )
        except miibo.MiiboAPIError:
            raised = True
    ok = raised and len(calls) == 1
    _check("c2 401 → MiiboAPIError after 1 attempt (no retry)", ok,
           f"raised={raised}, attempts={len(calls)}")


def test_call_503_retries_then_fails():
    err_body = b'{"error": "service unavailable"}'
    with _mock_urlopen([(503, err_body), (503, err_body), (503, err_body)]) as calls:
        raised = False
        try:
            miibo.call_ai_kamiyama(
                "x", api_key="k", agent_id="a", max_retries=2,
            )
        except miibo.MiiboAPIError:
            raised = True
    ok = raised and len(calls) == 3
    _check("c3 503 retries 3 times (max_retries=2), then MiiboAPIError", ok,
           f"raised={raised}, attempts={len(calls)}")


def test_call_503_then_200_succeeds():
    err_body = b'{"error": "transient"}'
    good = _good_response_json("回復しました")
    with _mock_urlopen([(503, err_body), good]) as calls:
        resp = miibo.call_ai_kamiyama(
            "x", api_key="k", agent_id="a", max_retries=2,
        )
    ok = resp.utterance_response == "回復しました" and len(calls) == 2
    _check("c4 503 then 200 → success on 2nd attempt", ok,
           f"resp={resp.utterance_response!r}, attempts={len(calls)}")


def test_call_network_error_retries():
    """URLError (network failure) も retry 対象"""
    net_err = urllib.error.URLError("network down")
    good = _good_response_json("ok")
    with _mock_urlopen([net_err, good]) as calls:
        resp = miibo.call_ai_kamiyama(
            "x", api_key="k", agent_id="a", max_retries=2,
        )
    ok = resp.utterance_response == "ok" and len(calls) == 2
    _check("c5 URLError → retry → success", ok,
           f"attempts={len(calls)}")


def test_call_200_but_no_utterance_field():
    bad = json.dumps({"bestResponse": {}}).encode("utf-8")
    with _mock_urlopen([bad]):
        raised = False
        try:
            miibo.call_ai_kamiyama("x", api_key="k", agent_id="a")
        except miibo.MiiboAPIError:
            raised = True
    _check("c6 200 but missing utterance → MiiboAPIError", raised)


def test_call_redacts_key_in_error():
    """Error message must NOT leak the literal API key."""
    secret_key = "SECRET_KEY_VALUE_99c85"
    err_body = f'{{"error": "auth failed for api_key={secret_key}"}}'.encode("utf-8")
    with _mock_urlopen([(401, err_body)]):
        captured = ""
        try:
            miibo.call_ai_kamiyama(
                "x", api_key=secret_key, agent_id="a", max_retries=0,
            )
        except miibo.MiiboAPIError as e:
            captured = str(e)
    ok = secret_key not in captured and "[REDACTED_MIIBO_KEY]" in captured
    _check("c7 4xx error message has redacted key", ok,
           f"captured={captured!r}")


# ---------------------------------------------------------------------------
# (d) reset_short_term_memory
# ---------------------------------------------------------------------------

def test_reset_sends_empty_utterance():
    with _mock_urlopen([_good_response_json()]) as calls:
        miibo.reset_short_term_memory(api_key="k", agent_id="a")
    ok = len(calls) == 1 and calls[0]["body"]["utterance"] == ""
    _check("d1 reset_short_term_memory: empty utterance posted", ok,
           f"body utt={calls[0]['body'].get('utterance')!r}")


def test_reset_swallows_errors():
    """reset failures must NOT propagate (it's best-effort)."""
    with _mock_urlopen([(500, b"oops")]):
        try:
            miibo.reset_short_term_memory(api_key="k", agent_id="a")
            ok = True
        except Exception:
            ok = False
    _check("d2 reset swallows HTTP errors (best-effort)", ok)


# ---------------------------------------------------------------------------
# Test runner
# ---------------------------------------------------------------------------

def main() -> int:
    print("Page 6 — miibo lib tests")
    print()
    print("(a) Credentials:")
    test_credentials_missing_key_raises()
    test_credentials_missing_agent_raises()
    test_credentials_present_returns_tuple()
    print()
    print("(b) redact_miibo_key:")
    test_redact_replaces_literal_key()
    test_redact_empty_inputs_passthrough()
    test_redact_no_match_unchanged()
    print()
    print("(c) call_ai_kamiyama:")
    test_call_happy_path()
    test_call_4xx_no_retry()
    test_call_503_retries_then_fails()
    test_call_503_then_200_succeeds()
    test_call_network_error_retries()
    test_call_200_but_no_utterance_field()
    test_call_redacts_key_in_error()
    print()
    print("(d) reset_short_term_memory:")
    test_reset_sends_empty_utterance()
    test_reset_swallows_errors()
    print()
    print(f"=== {PASS} passed, {FAIL} failed ===")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
