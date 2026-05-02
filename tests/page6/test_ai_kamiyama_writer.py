"""Unit tests for scripts/page6/ai_kamiyama_writer.py.

Run::

    python3 -m tests.page6.test_ai_kamiyama_writer

miibo API is fully mocked at the lib level. No real network call.
"""

from __future__ import annotations

import json
import sys

from scripts.lib import miibo
from scripts.page6 import ai_kamiyama_writer, prompts

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
# Mock infra
# ---------------------------------------------------------------------------

class _StubMiibo:
    """Replace miibo.call_ai_kamiyama + reset_short_term_memory."""

    def __init__(self, *, response_text=None, raise_exc=None,
                 elapsed_ms=120, raw=None):
        self.response_text = response_text
        self.raise_exc = raise_exc
        self.elapsed_ms = elapsed_ms
        self.raw = raw
        self.call_count = 0
        self.reset_count = 0
        self._call_orig = None
        self._reset_orig = None

    def __enter__(self):
        self._call_orig = miibo.call_ai_kamiyama
        self._reset_orig = miibo.reset_short_term_memory

        def _stub_call(utterance, **kwargs):
            self.call_count += 1
            self.last_utterance = utterance
            if self.raise_exc is not None:
                raise self.raise_exc
            return miibo.MiiboResponse(
                utterance_response=self.response_text or "",
                raw_response=self.raw or {"bestResponse": {"utterance": self.response_text}},
                elapsed_ms=self.elapsed_ms,
            )

        def _stub_reset(**kwargs):
            self.reset_count += 1

        miibo.call_ai_kamiyama = _stub_call
        miibo.reset_short_term_memory = _stub_reset
        return self

    def __exit__(self, *exc):
        miibo.call_ai_kamiyama = self._call_orig
        miibo.reset_short_term_memory = self._reset_orig


def _sample_article() -> dict:
    return {
        "url": "https://example.test/article",
        "title": "サティ生誕160年記念 青柳いづみこ×高橋悠治",
        "source_name": "春秋社",
        "description": "サティ生誕160年記念のトークイベント開催。" * 3,
        "pub_date": "2026-04-28",
    }


def _good_response_json() -> str:
    return json.dumps({
        "column_title": "間（ま）の音楽",
        "column_body": "サティが愛した『家具の音楽』とは何か。" + ("あ" * 250),
    }, ensure_ascii=False)


# ---------------------------------------------------------------------------
# (a) Happy path
# ---------------------------------------------------------------------------

def test_happy_path():
    with _StubMiibo(response_text=_good_response_json(), elapsed_ms=234) as stub:
        result = ai_kamiyama_writer.write_column(_sample_article())
    ok = (
        result["column_title"] == "間（ま）の音楽"
        and result["column_body"].startswith("サティが愛した")
        and result["is_fallback"] is False
        and result["ai_kamiyama_called"] is True
        and result["ai_kamiyama_failed"] is False
        and result["fallback_used"] is False
        and result["elapsed_ms"] == 234
        and stub.call_count == 1
    )
    _check("a1 happy path: parsed JSON, all flags correct", ok,
           f"is_fallback={result['is_fallback']}, elapsed={result['elapsed_ms']}")


def test_strips_code_fence():
    fenced = "```json\n" + _good_response_json() + "\n```"
    with _StubMiibo(response_text=fenced):
        result = ai_kamiyama_writer.write_column(_sample_article())
    _check("a2 strips ```json fences from response",
           result["column_title"] == "間（ま）の音楽")


def test_reset_called_before_main():
    with _StubMiibo(response_text=_good_response_json()) as stub:
        ai_kamiyama_writer.write_column(_sample_article())
    _check("a3 reset_short_term_memory called once before main call",
           stub.reset_count == 1 and stub.call_count == 1,
           f"reset={stub.reset_count}, call={stub.call_count}")


def test_skip_reset_flag():
    with _StubMiibo(response_text=_good_response_json()) as stub:
        ai_kamiyama_writer.write_column(_sample_article(), skip_reset=True)
    _check("a4 skip_reset=True suppresses reset call",
           stub.reset_count == 0 and stub.call_count == 1)


def test_utterance_contains_article_meta():
    """Utterance built from prompt template should include article fields."""
    with _StubMiibo(response_text=_good_response_json()) as stub:
        ai_kamiyama_writer.write_column(_sample_article())
    utt = stub.last_utterance
    ok = (
        "サティ生誕160年" in utt
        and "春秋社" in utt
        and "500 字前後" in utt
        and "JSON" in utt
    )
    _check("a5 utterance includes title + source + 500字 + JSON instruction", ok,
           f"utt[:80]={utt[:80]!r}")


# ---------------------------------------------------------------------------
# (b) Fallback paths
# ---------------------------------------------------------------------------

def test_api_error_fallback_休載():
    with _StubMiibo(raise_exc=miibo.MiiboAPIError("conn refused")) as stub:
        result = ai_kamiyama_writer.write_column(_sample_article())
    ok = (
        result["is_fallback"] is True
        and result["column_title"] == prompts.FALLBACK_TITLE
        and result["column_body"] == prompts.FALLBACK_BODY
        and result["ai_kamiyama_called"] is True
        and result["ai_kamiyama_failed"] is True
        and result["fallback_used"] is True
    )
    _check("b1 MiiboAPIError → 休載 fallback (is_fallback=True)", ok,
           f"title={result['column_title']!r}")


def test_non_json_response_uses_raw_as_body():
    """Spec: JSON parse 失敗時は生応答を column_body に、
    column_title=本日の一筆、is_fallback=False（応答自体は得られている）"""
    raw_text = "今朝の記事を読んで、ふと思ったことがあります。" + ("あ" * 200)
    with _StubMiibo(response_text=raw_text):
        result = ai_kamiyama_writer.write_column(_sample_article())
    ok = (
        result["is_fallback"] is False  # ← 応答が得られているから休載扱いではない
        and result["column_title"] == "本日の一筆"
        and "今朝の記事を読んで" in result["column_body"]
        and result["ai_kamiyama_called"] is True
        and result["ai_kamiyama_failed"] is False
    )
    _check("b2 non-JSON response → raw as body, title=本日の一筆, NOT fallback", ok,
           f"is_fallback={result['is_fallback']}, title={result['column_title']!r}")


def test_empty_response_fallback():
    with _StubMiibo(response_text=""):
        # MiiboResponse with empty utterance — but call_ai_kamiyama actually
        # raises MiiboAPIError for empty utterance. Let's simulate the raw
        # path: empty string as response_text.
        # Note: in reality, miibo lib raises before we get here, but we
        # test the writer's defensive empty-string handling.
        result = ai_kamiyama_writer.write_column(_sample_article())
    ok = (
        result["is_fallback"] is True
        and result["column_title"] == prompts.FALLBACK_TITLE
    )
    _check("b3 empty response_text → 休載 fallback", ok,
           f"is_fallback={result['is_fallback']}")


def test_missing_column_body_falls_to_raw():
    """JSON valid but missing column_body → raw fallback."""
    bad = json.dumps({"column_title": "タイトルだけ"}, ensure_ascii=False)
    with _StubMiibo(response_text=bad):
        result = ai_kamiyama_writer.write_column(_sample_article())
    # Should treat as JSON parse failure (since required key missing)
    # and use raw as body.
    ok = (
        result["is_fallback"] is False
        and result["column_title"] == "本日の一筆"
        and "タイトルだけ" in result["column_body"]
    )
    _check("b4 missing column_body in JSON → raw fallback path", ok,
           f"is_fallback={result['is_fallback']}, title={result['column_title']!r}, "
           f"body={result['column_body'][:50]!r}")


# ---------------------------------------------------------------------------
# Test runner
# ---------------------------------------------------------------------------

def main() -> int:
    print("Page 6 — ai_kamiyama_writer tests")
    print()
    print("(a) Happy path:")
    test_happy_path()
    test_strips_code_fence()
    test_reset_called_before_main()
    test_skip_reset_flag()
    test_utterance_contains_article_meta()
    print()
    print("(b) Fallback paths:")
    test_api_error_fallback_休載()
    test_non_json_response_uses_raw_as_body()
    test_empty_response_fallback()
    test_missing_column_body_falls_to_raw()
    print()
    print(f"=== {PASS} passed, {FAIL} failed ===")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
