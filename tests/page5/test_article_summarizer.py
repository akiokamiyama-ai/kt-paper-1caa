"""Unit tests for scripts/page5/article_summarizer.py (C155, Sprint 13, 2026-08-10).

Tests:
  a) truncate_to_chars の境界挙動
  b) _build_input_text: body / description の組み立て
  c) summarize_article: 正常系（LLM モック）
  d) summarize_article: 入力が短すぎる → fallback
  e) summarize_article: LLM 例外 → fallback
  f) summarize_article: LLM 応答が空 → fallback
  g) 出力の HARD_MAX_CHARS 上限

Run::

    python3 -m tests.page5.test_article_summarizer
"""

from __future__ import annotations

import sys

from scripts.page5 import article_summarizer as summ

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


def _article(**kw) -> dict:
    base = {
        "title": "A quietly radical rethink of corporate memory",
        "source_name": "The Economist",
        "url": "https://example.test/a",
        "description": "あ" * 200,
    }
    base.update(kw)
    return base


# ---------------------------------------------------------------------------
# (a) truncate_to_chars
# ---------------------------------------------------------------------------

def test_truncate_under_limit_unchanged():
    _check("a1 limit 以下ならそのまま（… を付けない）",
           summ.truncate_to_chars("abc", 10) == "abc")


def test_truncate_over_limit_appends_ellipsis():
    out = summ.truncate_to_chars("あ" * 50, 10)
    _check("a2 limit 超過で 10 字 + …",
           out == "あ" * 10 + "…", f"got {out!r}")


def test_truncate_exact_limit_no_ellipsis():
    out = summ.truncate_to_chars("あ" * 10, 10)
    _check("a3 ちょうど limit なら … を付けない", out == "あ" * 10)


def test_truncate_empty():
    _check("a4 空文字は空文字", summ.truncate_to_chars("", 10) == "")


# ---------------------------------------------------------------------------
# (b) _build_input_text
# ---------------------------------------------------------------------------

def test_input_prefers_body_and_prepends_desc():
    art = _article(description="概要テキスト", body="本文" * 100)
    out = summ._build_input_text(art)
    _check("b1 desc と body が両方あれば連結される",
           out.startswith("概要テキスト") and "本文" in out, f"got {out[:40]!r}")


def test_input_falls_back_to_description():
    art = _article(description="概要のみ" * 30, body=None)
    out = summ._build_input_text(art)
    _check("b2 body が無ければ description を使う",
           "概要のみ" in out, f"got {out[:40]!r}")


def test_input_strips_html():
    art = _article(description="<p>タグ入り &amp; エンティティ</p>", body=None)
    out = summ._build_input_text(art)
    _check("b3 HTML タグ除去 + エンティティ復号",
           "<p>" not in out and "&" in out and "タグ入り" in out, f"got {out!r}")


def test_input_respects_excerpt_limit():
    art = _article(description="", body="x" * 9000)
    out = summ._build_input_text(art)
    _check("b4 INPUT_EXCERPT_LIMIT で打ち切る",
           len(out) == summ.INPUT_EXCERPT_LIMIT, f"len={len(out)}")


# ---------------------------------------------------------------------------
# (c) 正常系
# ---------------------------------------------------------------------------

def test_summarize_uses_llm_output():
    calls: list[tuple[str, str]] = []

    def fake_llm(system: str, user: str) -> str:
        calls.append((system, user))
        return "これはLLMが生成した日本語サマリである。" * 3

    art = _article(body="本文" * 200)
    out = summ.summarize_article(art, llm_caller=fake_llm)
    _check("c1 LLM 出力がそのまま summary になる",
           out["summary"].startswith("これはLLMが生成した"), f"got {out['summary'][:30]!r}")
    _check("c2 is_fallback=False", out["is_fallback"] is False)
    _check("c3 LLM は 1 回だけ呼ばれる", len(calls) == 1, f"got {len(calls)}")
    _check("c4 user prompt にタイトルとソースが入る",
           "The Economist" in calls[0][1] and "corporate memory" in calls[0][1])
    _check("c5 system prompt が論評を禁じている",
           "解釈・評価・意見" in calls[0][0])


def test_summarize_prefers_title_ja():
    seen: dict = {}

    def fake_llm(system: str, user: str) -> str:
        seen["user"] = user
        return "サマリ" * 60

    art = _article(title_ja="企業の記憶をめぐる静かな再考", body="本文" * 200)
    summ.summarize_article(art, llm_caller=fake_llm)
    _check("c6 title_ja があればそちらを prompt に渡す",
           "企業の記憶をめぐる静かな再考" in seen["user"])


# ---------------------------------------------------------------------------
# (d)(e)(f) fallback 経路
# ---------------------------------------------------------------------------

def test_short_input_falls_back_without_calling_llm():
    called = {"n": 0}

    def fake_llm(system: str, user: str) -> str:
        called["n"] += 1
        return "should not be called"

    art = _article(description="短い", body=None)
    out = summ.summarize_article(art, llm_caller=fake_llm)
    _check("d1 入力が MIN_INPUT_CHARS 未満 → LLM を呼ばない", called["n"] == 0)
    _check("d2 is_fallback=True", out["is_fallback"] is True)
    _check("d3 cost_usd=0.0", out["cost_usd"] == 0.0)


def test_llm_exception_falls_back_to_description():
    def boom(system: str, user: str) -> str:
        raise RuntimeError("API timeout")

    art = _article(description="概要" * 100, body=None)
    out = summ.summarize_article(art, llm_caller=boom)
    _check("e1 LLM 例外 → is_fallback=True", out["is_fallback"] is True)
    _check("e2 fallback は description の truncate",
           out["summary"].startswith("概要") and len(out["summary"]) <= summ.TARGET_MAX_CHARS + 1,
           f"len={len(out['summary'])}")


def test_empty_llm_output_falls_back():
    art = _article(description="概要" * 100, body=None)
    out = summ.summarize_article(art, llm_caller=lambda s, u: "   ")
    _check("f1 LLM 応答が空白のみ → fallback", out["is_fallback"] is True)
    _check("f2 fallback でも summary は非空", bool(out["summary"]))


# ---------------------------------------------------------------------------
# (g) 上限
# ---------------------------------------------------------------------------

def test_output_capped_at_hard_max():
    art = _article(body="本文" * 200)
    out = summ.summarize_article(art, llm_caller=lambda s, u: "あ" * 2000)
    _check("g1 HARD_MAX_CHARS で打ち切る（+1 は … の分）",
           len(out["summary"]) == summ.HARD_MAX_CHARS + 1,
           f"len={len(out['summary'])}")


def test_target_band_constants_sane():
    _check("g2 目安帯 300-400 字、hard cap はそれ以上",
           summ.TARGET_MIN_CHARS == 300
           and summ.TARGET_MAX_CHARS == 400
           and summ.HARD_MAX_CHARS > summ.TARGET_MAX_CHARS)
    _check("g3 tag は page5.article_summary",
           summ.SUMMARY_TAG == "page5.article_summary", summ.SUMMARY_TAG)


def main() -> int:
    print("article_summarizer tests (C155, Sprint 13, 2026-08-10)")
    print()
    print("(a) truncate_to_chars:")
    test_truncate_under_limit_unchanged()
    test_truncate_over_limit_appends_ellipsis()
    test_truncate_exact_limit_no_ellipsis()
    test_truncate_empty()
    print()
    print("(b) _build_input_text:")
    test_input_prefers_body_and_prepends_desc()
    test_input_falls_back_to_description()
    test_input_strips_html()
    test_input_respects_excerpt_limit()
    print()
    print("(c) 正常系:")
    test_summarize_uses_llm_output()
    test_summarize_prefers_title_ja()
    print()
    print("(d)(e)(f) fallback 経路:")
    test_short_input_falls_back_without_calling_llm()
    test_llm_exception_falls_back_to_description()
    test_empty_llm_output_falls_back()
    print()
    print("(g) 上限と定数:")
    test_output_capped_at_hard_max()
    test_target_band_constants_sane()
    print()
    print(f"=== {PASS} passed, {FAIL} failed ===")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
