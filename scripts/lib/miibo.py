"""miibo (api-mebo.dev) wrapper for AI 神山 column generation.

Mirrors the design of ``scripts/lib/llm.py`` for the Anthropic API:

1. **Credential validator** — reads ``MIIBO_API_KEY`` and ``MIIBO_AGENT_ID``
   from the environment, refuses to proceed if missing. Never accepts
   credentials from a config file or commit.

2. **call_ai_kamiyama()** — single-turn POST to ``https://api-mebo.dev/api``.
   Wraps urllib.request with retry/backoff on transient errors (503, 504, 429).

3. **reset_short_term_memory()** — sends an empty utterance to clear the
   agent's conversation context. Page VI is a fresh-each-morning ritual,
   so we reset before every real call.

4. **redact_miibo_key()** — string-substitutes the literal key value with
   ``[REDACTED_MIIBO_KEY]`` in error messages. Unlike Anthropic's
   ``sk-ant-`` prefix, miibo keys have no distinctive prefix, so we use
   value-substitution rather than regex.

The miibo API is bypass for the Anthropic daily-cap accounting since it
runs on a separate billing system (神山さんの会社の miibo 契約定額枠内).
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MIIBO_API_KEY_ENV = "MIIBO_API_KEY"
MIIBO_AGENT_ID_ENV = "MIIBO_AGENT_ID"

API_ENDPOINT = "https://api-mebo.dev/api"

DEFAULT_TIMEOUT_SECONDS = 30
DEFAULT_MAX_RETRIES = 2
DEFAULT_UID = "tribune_daily_v1"

# api-mebo.dev は Cloudflare 配下で、デフォルト Python-urllib UA を 1010 で
# 弾く。RSS driver / CleverHiker 等で使っているのと同じ Chrome UA を採用。
# (2026-05-02 検証で確認、403 → 200 に解消)
_BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# 4xx は即 fail (auth error 等は retry しても回復しない)、
# 5xx と 429 のみ retry 対象（spec 通り）。
_RETRYABLE_HTTP_CODES: frozenset[int] = frozenset({429, 500, 502, 503, 504})


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class MiiboAPIError(RuntimeError):
    """miibo API 呼び出し失敗時の例外。caller は fallback を起動する。"""


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class MiiboResponse:
    utterance_response: str
    raw_response: dict
    elapsed_ms: int


# ---------------------------------------------------------------------------
# Credentials
# ---------------------------------------------------------------------------

def get_miibo_credentials() -> tuple[str, str]:
    """Read and validate miibo credentials from environment.

    Returns ``(api_key, agent_id)``. Raises ``RuntimeError`` with an
    actionable message if either is missing.
    """
    key = os.environ.get(MIIBO_API_KEY_ENV)
    agent_id = os.environ.get(MIIBO_AGENT_ID_ENV)
    if not key:
        raise RuntimeError(
            f"{MIIBO_API_KEY_ENV} environment variable not set. "
            f"Set it in ~/.bashrc (e.g. `export {MIIBO_API_KEY_ENV}=...`) "
            f"and chmod 600 the file. Never commit the key. Never write it "
            f"to config/site_overrides.toml or any tracked file."
        )
    if not agent_id:
        raise RuntimeError(
            f"{MIIBO_AGENT_ID_ENV} environment variable not set. "
            f"Set it in ~/.bashrc alongside {MIIBO_API_KEY_ENV}."
        )
    return key, agent_id


def redact_miibo_key(text: str, api_key: str) -> str:
    """Replace the literal key value with ``[REDACTED_MIIBO_KEY]``.

    Unlike Anthropic's ``sk-ant-`` keys, miibo keys have no distinctive
    prefix (e.g. ``99c85...``-style hex strings), so regex prefix matching
    isn't reliable. Value-substitution is the safest path.
    """
    if not api_key or not text:
        return text
    return text.replace(api_key, "[REDACTED_MIIBO_KEY]")


# ---------------------------------------------------------------------------
# Internal HTTP
# ---------------------------------------------------------------------------

def _post_json(
    url: str,
    body: dict,
    *,
    timeout: int,
) -> tuple[int, dict | None, str]:
    """POST ``body`` as JSON. Returns ``(http_status, parsed_body, raw_text)``.

    Network-level failures (connection refused, DNS, timeout) are raised
    as ``MiiboAPIError``. HTTP errors (4xx, 5xx) are returned as a status
    code so the caller can decide whether to retry.
    """
    payload = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url, data=payload,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": _BROWSER_USER_AGENT,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            status = resp.getcode()
            try:
                parsed = json.loads(raw) if raw else None
            except json.JSONDecodeError:
                parsed = None
            return status, parsed, raw
    except urllib.error.HTTPError as e:
        # HTTPError carries a status — return it for the retry decision.
        try:
            raw = e.read().decode("utf-8", errors="replace")
        except Exception:
            raw = ""
        try:
            parsed = json.loads(raw) if raw else None
        except json.JSONDecodeError:
            parsed = None
        return e.code, parsed, raw
    except (urllib.error.URLError, TimeoutError) as e:
        raise MiiboAPIError(f"network error: {type(e).__name__}: {e}") from e


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def reset_short_term_memory(
    *,
    api_key: str | None = None,
    agent_id: str | None = None,
    uid: str = DEFAULT_UID,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
) -> None:
    """Send an empty utterance to clear the agent's conversation context.

    Tribune's Page VI is a fresh-each-morning ritual: yesterday's
    conversation must not bleed into today. The miibo agent treats an
    empty utterance as a session-reset signal.

    Failures here are non-fatal — the caller can still attempt the real
    utterance; in the worst case the agent carries over yesterday's
    context. Logged so it's observable.
    """
    if api_key is None or agent_id is None:
        api_key, agent_id = get_miibo_credentials()
    body = {
        "api_key": api_key,
        "agent_id": agent_id,
        "utterance": "",
        "uid": uid,
    }
    try:
        status, _, raw = _post_json(API_ENDPOINT, body, timeout=timeout)
        if status >= 400:
            # Best-effort: surface the failure but don't raise.
            safe = redact_miibo_key(raw, api_key)
            print(
                f"[miibo] reset_short_term_memory: HTTP {status}, body={safe[:200]}",
                end="\n",
            )
    except MiiboAPIError as e:
        # Don't propagate: reset is best-effort.
        safe = redact_miibo_key(str(e), api_key)
        print(f"[miibo] reset_short_term_memory: {safe}", end="\n")


def call_ai_kamiyama(
    utterance: str,
    *,
    api_key: str | None = None,
    agent_id: str | None = None,
    uid: str = DEFAULT_UID,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
    max_retries: int = DEFAULT_MAX_RETRIES,
) -> MiiboResponse:
    """Single-turn call to the AI 神山 agent.

    Parameters
    ----------
    utterance :
        The user message (Japanese) to send to the agent. Constructed by
        ``scripts.page5.ai_kamiyama_writer`` from the prompt template.
    api_key, agent_id :
        Optional explicit credentials (mostly for tests). Defaults to env.
    uid :
        Conversation identifier. Stable per Tribune persona — keeping the
        same uid lets miibo group sessions for analytics, but combined
        with reset_short_term_memory() each morning is a fresh start.
    timeout :
        Per-attempt HTTP timeout in seconds.
    max_retries :
        Number of retry attempts beyond the first try, with exponential
        backoff (1s, 2s, ...). Only 5xx and 429 trigger retry.

    Raises
    ------
    MiiboAPIError
        After exhausting retries, or on 4xx (auth / payload errors —
        retrying won't help).
    """
    if api_key is None or agent_id is None:
        api_key, agent_id = get_miibo_credentials()

    body = {
        "api_key": api_key,
        "agent_id": agent_id,
        "utterance": utterance,
        "uid": uid,
    }

    last_err: str = ""
    last_status: int | None = None
    for attempt in range(max_retries + 1):
        start = time.monotonic()
        try:
            status, parsed, raw = _post_json(API_ENDPOINT, body, timeout=timeout)
        except MiiboAPIError as e:
            # Network-level error
            last_err = redact_miibo_key(str(e), api_key)
            if attempt < max_retries:
                time.sleep(2 ** attempt)
                continue
            raise MiiboAPIError(
                f"network failure after {max_retries + 1} attempts: {last_err}"
            ) from None

        elapsed_ms = int((time.monotonic() - start) * 1000)
        last_status = status

        # Success path
        if 200 <= status < 300:
            if not isinstance(parsed, dict):
                safe = redact_miibo_key(raw, api_key)
                raise MiiboAPIError(
                    f"HTTP {status} but body was not JSON: {safe[:200]}"
                )
            best = parsed.get("bestResponse") or {}
            utt = best.get("utterance")
            if not isinstance(utt, str) or not utt.strip():
                safe = redact_miibo_key(raw, api_key)
                raise MiiboAPIError(
                    f"HTTP {status} but bestResponse.utterance missing: {safe[:200]}"
                )
            return MiiboResponse(
                utterance_response=utt,
                raw_response=parsed,
                elapsed_ms=elapsed_ms,
            )

        # Retryable HTTP errors
        if status in _RETRYABLE_HTTP_CODES and attempt < max_retries:
            safe = redact_miibo_key(raw, api_key)
            print(
                f"[miibo] HTTP {status}, retry {attempt + 1}/{max_retries}: "
                f"{safe[:200]}",
            )
            time.sleep(2 ** attempt)
            continue

        # 4xx (other than 429) or final retry exhausted
        safe = redact_miibo_key(raw, api_key)
        raise MiiboAPIError(
            f"HTTP {status} after {attempt + 1} attempt(s): {safe[:300]}"
        )

    # Defensive — loop structure shouldn't reach here.
    raise MiiboAPIError(
        f"unreachable: exhausted retries (last_status={last_status})"
    )
