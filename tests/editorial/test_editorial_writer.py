"""Unit tests for editorial.editorial_writer (Sprint 4 Phase 3, 2026-05-03).

Tests:
  a) Normal path: JSON {"body": "..."} → is_fallback=False, body extracted
  b) API exception → is_fallback=True
  c) JSON parse failure → is_fallback=True
  d) Body too short (<50) → is_fallback=True
  e) Body too long (>200) → is_fallback=True
  f) Empty body string → is_fallback=True
  g) Banned-phrase leakage → is_fallback=True with reason
  h) Code-fence wrapped JSON tolerated
  i) BANNED_PHRASES + length bounds defined
  j) Prompt template renders context_json correctly

Run::

    python3 -m tests.editorial.test_editorial_writer
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass

from scripts.editorial import editorial_writer
from scripts.editorial import prompts as editorial_prompts

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


# Mock ClaudeResponse-shaped object
@dataclass
class FakeClaudeResponse:
    text: str
    model: str = "claude-sonnet-4-6"
    input_tokens: int = 100
    output_tokens: int = 50
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0
    cost_usd: float = 0.001
    stop_reason: str = "end_turn"
    raw_id: str = "fake_id"


def _install_mock_call(text: str | None = None, raise_exc: Exception | None = None):
    """Patch llm.call_claude_with_retry on the editorial_writer namespace."""
    original = editorial_writer.llm.call_claude_with_retry

    def fake(*args, **kwargs):
        if raise_exc is not None:
            raise raise_exc
        return FakeClaudeResponse(text=text or "")
    editorial_writer.llm.call_claude_with_retry = fake
    return original


def _restore(original):
    editorial_writer.llm.call_claude_with_retry = original


# ---------------------------------------------------------------------------
# (a) Normal path
# ---------------------------------------------------------------------------

def test_normal_path():
    body = "本紙は今朝、世界銀行のUターンと中堅製造業の参照アーキテクチャを並べた。同じ語彙（実装パートナー、参照リスト）が国家予算の規模と単独企業の調達の両方で響くこと、その共鳴に静かに目を留めたい。"
    text = json.dumps({"body": body}, ensure_ascii=False)
    orig = _install_mock_call(text=text)
    try:
        result = editorial_writer.write_editorial({"page1_top": "test"})
    finally:
        _restore(orig)
    _check("a1 normal path: is_fallback=False",
           result["is_fallback"] is False,
           f"got {result['is_fallback']}")
    _check("a2 body extracted from JSON", result["body"] == body)
    _check("a3 cost_usd populated", result["cost_usd"] > 0,
           f"got {result['cost_usd']}")
    _check("a4 elapsed_ms is int", isinstance(result["elapsed_ms"], int))


# ---------------------------------------------------------------------------
# (b) API exception
# ---------------------------------------------------------------------------

def test_api_exception_fallback():
    orig = _install_mock_call(raise_exc=RuntimeError("network down"))
    try:
        result = editorial_writer.write_editorial({})
    finally:
        _restore(orig)
    _check("b1 API exception → is_fallback=True", result["is_fallback"] is True)
    _check("b2 body is empty on api error", result["body"] == "")
    _check("b3 fallback_reason includes RuntimeError",
           "RuntimeError" in result.get("fallback_reason", ""))


# ---------------------------------------------------------------------------
# (c) JSON parse failure
# ---------------------------------------------------------------------------

def test_json_parse_failure_fallback():
    orig = _install_mock_call(text="this is not json at all, just prose")
    try:
        result = editorial_writer.write_editorial({})
    finally:
        _restore(orig)
    _check("c1 unparsable text → is_fallback=True", result["is_fallback"] is True)
    _check("c2 body is empty on parse error", result["body"] == "")


# ---------------------------------------------------------------------------
# (d) Too short body
# ---------------------------------------------------------------------------

def test_too_short_body_fallback():
    text = json.dumps({"body": "短い。"}, ensure_ascii=False)
    orig = _install_mock_call(text=text)
    try:
        result = editorial_writer.write_editorial({})
    finally:
        _restore(orig)
    _check("d1 body <50 chars → is_fallback=True", result["is_fallback"] is True)
    _check("d2 fallback_reason mentions 'too short'",
           "too short" in result.get("fallback_reason", ""),
           f"reason={result.get('fallback_reason')}")


# ---------------------------------------------------------------------------
# (e) Too long body
# ---------------------------------------------------------------------------

def test_too_long_body_fallback():
    long_body = "あ" * 250  # 250 chars > 200
    text = json.dumps({"body": long_body}, ensure_ascii=False)
    orig = _install_mock_call(text=text)
    try:
        result = editorial_writer.write_editorial({})
    finally:
        _restore(orig)
    _check("e1 body >200 chars → is_fallback=True", result["is_fallback"] is True)
    _check("e2 fallback_reason mentions 'too long'",
           "too long" in result.get("fallback_reason", ""))


# ---------------------------------------------------------------------------
# (f) Empty body
# ---------------------------------------------------------------------------

def test_empty_body_fallback():
    text = json.dumps({"body": ""}, ensure_ascii=False)
    orig = _install_mock_call(text=text)
    try:
        result = editorial_writer.write_editorial({})
    finally:
        _restore(orig)
    _check("f1 empty body → is_fallback=True", result["is_fallback"] is True)


# ---------------------------------------------------------------------------
# (g) Banned-phrase leakage
# ---------------------------------------------------------------------------

def test_banned_phrase_fallback():
    body = (
        "今朝の紙面では神山さんの問題意識が連続して現れていた。"
        "聞き上手の哲学が経営にどう接続するか、考えてみたい。これは余韻として残す。今朝の編集者から。"
    )
    text = json.dumps({"body": body}, ensure_ascii=False)
    orig = _install_mock_call(text=text)
    try:
        result = editorial_writer.write_editorial({})
    finally:
        _restore(orig)
    _check("g1 body containing 神山さん → is_fallback=True (banned phrase)",
           result["is_fallback"] is True)
    _check("g2 fallback_reason mentions 'banned phrase'",
           "banned" in result.get("fallback_reason", ""),
           f"reason={result.get('fallback_reason')}")


# ---------------------------------------------------------------------------
# (h) Code-fence wrapped JSON tolerated
# ---------------------------------------------------------------------------

def test_code_fenced_json_tolerated():
    body = "本紙は今朝、世界銀行のUターンと中堅製造業の参照アーキテクチャを並べた。同じ語彙が国家規模と単独企業の調達で響くことに、静かに目を留めたい。"
    inner = json.dumps({"body": body}, ensure_ascii=False)
    text = f"```json\n{inner}\n```"
    orig = _install_mock_call(text=text)
    try:
        result = editorial_writer.write_editorial({})
    finally:
        _restore(orig)
    _check("h1 fenced ```json ... ``` parsed correctly",
           result["is_fallback"] is False and result["body"] == body,
           f"is_fallback={result['is_fallback']}, body[:30]={result['body'][:30]!r}")


# ---------------------------------------------------------------------------
# (i) Constants sanity
# ---------------------------------------------------------------------------

def test_constants_sanity():
    _check("i1 MIN_BODY_CHARS == 50", editorial_prompts.MIN_BODY_CHARS == 50)
    _check("i2 MAX_BODY_CHARS == 200", editorial_prompts.MAX_BODY_CHARS == 200)
    _check("i3 BANNED_PHRASES contains '聞き上手' and '神山さん'",
           "聞き上手" in editorial_prompts.BANNED_PHRASES
           and "神山さん" in editorial_prompts.BANNED_PHRASES)


# ---------------------------------------------------------------------------
# (j) Prompt template renders context
# ---------------------------------------------------------------------------

def test_prompt_template_includes_context_json():
    """Verify EDITORIAL_PROMPT_TEMPLATE.format(context_json=...) embeds the
    provided JSON string verbatim, with the surrounding instruction text intact.
    """
    fake_ctx = '{"page1_top": {"title": "marker_xyz123"}}'
    rendered = editorial_prompts.EDITORIAL_PROMPT_TEMPLATE.format(context_json=fake_ctx)
    has_marker = "marker_xyz123" in rendered
    has_voice_guidance = "Tribune" in rendered or "編集者" in rendered
    has_banned_list = "聞き上手" in rendered  # banned phrase enumerated in prompt
    _check("j1 context_json embedded into rendered prompt", has_marker)
    _check("j2 voice guidance present in prompt", has_voice_guidance)
    _check("j3 banned phrase '聞き上手' enumerated in prompt", has_banned_list)


def main() -> int:
    print("Editorial writer tests (Sprint 4 Phase 3, 2026-05-03)")
    print()
    print("(a) Normal path:")
    test_normal_path()
    print()
    print("(b) API exception:")
    test_api_exception_fallback()
    print()
    print("(c) JSON parse failure:")
    test_json_parse_failure_fallback()
    print()
    print("(d) Too short:")
    test_too_short_body_fallback()
    print()
    print("(e) Too long:")
    test_too_long_body_fallback()
    print()
    print("(f) Empty:")
    test_empty_body_fallback()
    print()
    print("(g) Banned-phrase leakage:")
    test_banned_phrase_fallback()
    print()
    print("(h) Code-fence tolerated:")
    test_code_fenced_json_tolerated()
    print()
    print("(i) Constants:")
    test_constants_sanity()
    print()
    print("(j) Prompt template:")
    test_prompt_template_includes_context_json()
    print()
    print(f"=== {PASS} passed, {FAIL} failed ===")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
