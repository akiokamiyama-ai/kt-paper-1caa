"""Unit tests for page1.lead_deck_writer (Sprint 5 task #3, 2026-05-04).

Tests use a llm.call_claude_with_retry mock so we don't hit the network.

Run::

    python3 -m tests.page1.test_lead_deck_writer
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass

from scripts.page1 import lead_deck_writer

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


@dataclass
class FakeClaudeResponse:
    text: str
    model: str = "claude-sonnet-4-6"
    input_tokens: int = 200
    output_tokens: int = 60
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0
    cost_usd: float = 0.002
    stop_reason: str = "end_turn"
    raw_id: str = "fake_id"


def _install_mock(text: str | None = None, raise_exc: Exception | None = None):
    original = lead_deck_writer.llm.call_claude_with_retry
    captured = {"system": None, "user": None}

    def fake(*, system, user, **kwargs):
        captured["system"] = system
        captured["user"] = user
        if raise_exc is not None:
            raise raise_exc
        return FakeClaudeResponse(text=text or "")
    lead_deck_writer.llm.call_claude_with_retry = fake
    return original, captured


def _restore(original):
    lead_deck_writer.llm.call_claude_with_retry = original


# ---------------------------------------------------------------------------
# (a) Normal path
# ---------------------------------------------------------------------------

def test_normal_path():
    deck = "本紙は今朝、世界銀行の産業政策報告書をめぐる解釈の乖離を取り上げる。介入主義派の希望的読解と報告書の実際の主張には距離があり、その精読をめぐって何が論点化されているか。"
    text = json.dumps({"deck": deck}, ensure_ascii=False)
    orig, _ = _install_mock(text=text)
    try:
        result = lead_deck_writer.write_lead_deck({
            "title": "Has the World Bank performed a U-turn on industrial policy?",
            "title_ja": "世界銀行は産業政策に関してUターンを行ったのでしょうか?",
            "description": "Interventionists who think so should read its new report more closely",
            "source_name": "The Economist",
        })
    finally:
        _restore(orig)
    _check("a1 normal: is_fallback=False", result["is_fallback"] is False,
           f"got {result['is_fallback']}")
    _check("a2 deck extracted from JSON", result["deck"] == deck)
    _check("a3 cost_usd populated", result["cost_usd"] > 0)
    _check("a4 elapsed_ms is int", isinstance(result["elapsed_ms"], int))


# ---------------------------------------------------------------------------
# (b) Length validation
# ---------------------------------------------------------------------------

def test_too_short_fallback():
    text = json.dumps({"deck": "短い。"}, ensure_ascii=False)  # < 30 chars
    orig, _ = _install_mock(text=text)
    try:
        result = lead_deck_writer.write_lead_deck({
            "title": "Test",
            "desc_ja": "本文の十分な長さの日本語テキストが80字くらいある場合のフォールバックパス、これくらいあれば十分長い。",
            "description": "The body text in English.",
            "source_name": "Test",
        })
    finally:
        _restore(orig)
    _check("b1 too short → is_fallback=True", result["is_fallback"] is True)
    _check("b2 fallback uses desc_ja truncate, not empty",
           result["deck"] != "" and "本文の十分な" in result["deck"])
    _check("b3 fallback_reason mentions 'too short'",
           "too short" in result.get("fallback_reason", ""))


def test_too_long_fallback():
    long_deck = "あ" * 200  # > 150
    text = json.dumps({"deck": long_deck}, ensure_ascii=False)
    orig, _ = _install_mock(text=text)
    try:
        result = lead_deck_writer.write_lead_deck({
            "desc_ja": "fallback テキスト",
            "title": "T",
        })
    finally:
        _restore(orig)
    _check("b4 too long → is_fallback=True", result["is_fallback"] is True)
    _check("b5 fallback_reason mentions 'too long'",
           "too long" in result.get("fallback_reason", ""))


# ---------------------------------------------------------------------------
# (c) API failure / parse failure
# ---------------------------------------------------------------------------

def test_api_exception():
    orig, _ = _install_mock(raise_exc=RuntimeError("network down"))
    try:
        result = lead_deck_writer.write_lead_deck({
            "title": "X",
            "desc_ja": "fallback として表示される本文の一部、これは80字程度で truncate される予定の長い文章として準備したサンプル。",
        })
    finally:
        _restore(orig)
    _check("c1 API exception → is_fallback=True", result["is_fallback"] is True)
    _check("c2 fallback uses desc_ja content",
           "fallback" in result["deck"])
    _check("c3 fallback_reason mentions RuntimeError",
           "RuntimeError" in result.get("fallback_reason", ""))


def test_json_parse_failure():
    orig, _ = _install_mock(text="this is not json")
    try:
        result = lead_deck_writer.write_lead_deck({
            "desc_ja": "JSON parse 失敗時のフォールバックテキスト、十分な長さで truncate される予定の本文サンプル。",
            "title": "T",
        })
    finally:
        _restore(orig)
    _check("d1 unparsable → is_fallback=True", result["is_fallback"] is True)
    _check("d2 deck non-empty (truncate of desc_ja)", len(result["deck"]) > 0)


# ---------------------------------------------------------------------------
# (d) Empty input handling
# ---------------------------------------------------------------------------

def test_empty_response():
    text = json.dumps({"deck": ""}, ensure_ascii=False)
    orig, _ = _install_mock(text=text)
    try:
        result = lead_deck_writer.write_lead_deck({
            "desc_ja": "空応答に対するフォールバック、80字以下に truncate される本文サンプル。",
            "title": "T",
        })
    finally:
        _restore(orig)
    _check("e1 empty deck → is_fallback=True", result["is_fallback"] is True)


def test_no_desc_ja_no_description_returns_empty_deck():
    """Article without desc_ja or description → fallback returns ''."""
    orig, _ = _install_mock(raise_exc=RuntimeError("err"))
    try:
        result = lead_deck_writer.write_lead_deck({
            "title": "T",
            # no desc_ja, no description
        })
    finally:
        _restore(orig)
    _check("e2 no desc_ja and no description → deck=''",
           result["is_fallback"] is True and result["deck"] == "")


# ---------------------------------------------------------------------------
# (e) JA / EN source handling
# ---------------------------------------------------------------------------

def test_ja_source_renders_ja_title_only_in_user_msg():
    """If title == title_ja (JA source), 日本語タイトル line is omitted."""
    orig, captured = _install_mock(
        text=json.dumps({"deck": "今朝の本紙は政府日銀の市場介入5兆円規模の推計を取り上げる。為替の地形変化は調達ラインに直接響く構図。"}, ensure_ascii=False),
    )
    try:
        lead_deck_writer.write_lead_deck({
            "title": "政府・日銀の市場介入 5兆円規模か",
            "title_ja": "政府・日銀の市場介入 5兆円規模か",
            "description": "民間会社の推計によると...",
            "source_name": "NHK ニュース 経済",
        })
    finally:
        _restore(orig)
    user_msg = captured["user"] or ""
    _check("f1 JA source: 日本語タイトル line omitted (no duplicate)",
           "日本語タイトル：" not in user_msg,
           f"snippet:\n{user_msg[:300]}")


def test_en_source_includes_ja_title_line():
    orig, captured = _install_mock(
        text=json.dumps({"deck": "本紙は世界銀行の産業政策報告書の解釈をめぐる議論を取り上げる。介入主義の希望的読解と報告書の主張の距離が論点。"}, ensure_ascii=False),
    )
    try:
        lead_deck_writer.write_lead_deck({
            "title": "Has the World Bank performed a U-turn on industrial policy?",
            "title_ja": "世界銀行は産業政策に関してUターンを行ったのでしょうか?",
            "description": "Interventionists who think so should read its new report more closely",
            "source_name": "The Economist",
        })
    finally:
        _restore(orig)
    user_msg = captured["user"] or ""
    _check("f2 EN source: 日本語タイトル line included",
           "日本語タイトル：世界銀行は産業政策" in user_msg)


# ---------------------------------------------------------------------------
# (f) Banned phrase guard
# ---------------------------------------------------------------------------

def test_banned_phrase_fallback():
    deck = (
        "本紙は今朝、神山さんの問題意識を取り上げる。"
        "聞き上手の哲学が経営にどう接続するか、構造と細部の往復で考える。"
    )
    text = json.dumps({"deck": deck}, ensure_ascii=False)
    orig, _ = _install_mock(text=text)
    try:
        result = lead_deck_writer.write_lead_deck({
            "desc_ja": "fallback の本文、80字以下にtruncateされる予定の十分な長さのテキスト。",
            "title": "T",
        })
    finally:
        _restore(orig)
    _check("g1 banned phrase '神山さん' → is_fallback=True",
           result["is_fallback"] is True)
    _check("g2 fallback_reason mentions 'banned phrase'",
           "banned" in result.get("fallback_reason", ""))


# ---------------------------------------------------------------------------
# (g) Code-fence wrapped JSON tolerated
# ---------------------------------------------------------------------------

def test_code_fenced_json_tolerated():
    deck = "本紙は今朝の世界銀行報告書の解釈分裂を取り上げる。介入主義派の希望的読解と報告書の主張の乖離が、産業政策の正当性をめぐる地形を映し出す。"
    inner = json.dumps({"deck": deck}, ensure_ascii=False)
    text = f"```json\n{inner}\n```"
    orig, _ = _install_mock(text=text)
    try:
        result = lead_deck_writer.write_lead_deck({
            "title": "T",
            "desc_ja": "fallback",
            "description": "...",
        })
    finally:
        _restore(orig)
    _check("h1 fenced JSON → parsed correctly",
           result["is_fallback"] is False and result["deck"] == deck)


# ---------------------------------------------------------------------------
# (h) Constants sanity
# ---------------------------------------------------------------------------

def test_constants_sanity():
    _check("i1 MIN_DECK_CHARS == 30", lead_deck_writer.MIN_DECK_CHARS == 30)
    _check("i2 MAX_DECK_CHARS == 150", lead_deck_writer.MAX_DECK_CHARS == 150)
    _check("i3 BANNED_PHRASES contains '神山さん' and '聞き上手'",
           "神山さん" in lead_deck_writer.BANNED_PHRASES
           and "聞き上手" in lead_deck_writer.BANNED_PHRASES)


def main() -> int:
    print("Lead deck writer tests — Sprint 5 task #3 (2026-05-04)")
    print()
    print("(a) Normal path:")
    test_normal_path()
    print()
    print("(b) Length validation:")
    test_too_short_fallback()
    test_too_long_fallback()
    print()
    print("(c) API / parse failure:")
    test_api_exception()
    test_json_parse_failure()
    print()
    print("(d) Empty input:")
    test_empty_response()
    test_no_desc_ja_no_description_returns_empty_deck()
    print()
    print("(e) JA / EN source title handling:")
    test_ja_source_renders_ja_title_only_in_user_msg()
    test_en_source_includes_ja_title_line()
    print()
    print("(f) Banned phrase guard:")
    test_banned_phrase_fallback()
    print()
    print("(g) Code-fence tolerated:")
    test_code_fenced_json_tolerated()
    print()
    print("(h) Constants:")
    test_constants_sanity()
    print()
    print(f"=== {PASS} passed, {FAIL} failed ===")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
