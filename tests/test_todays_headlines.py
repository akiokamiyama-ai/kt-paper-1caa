"""Unit tests for todays_headlines (Sprint 7 Phase 2 Step 1, 2026-05-19).

Tests:
  a) excluded_urls 除外 (Page I + Page III)
  b) eligible_sources フィルタ
  c) final_score 降順 + top_n
  d) format_summary：100 字以内 / 超過 / 空 description
  e) candidates_scored 空 → 空リスト
  f) 全候補 excluded → 空リスト
  g) page3_selections の article 取得（dataclass + dict 両形式）
  h) HEADLINES_ALLOWED_SOURCES の構成検証

Run::

    python3 -m tests.test_todays_headlines
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import date

from scripts.selector.todays_headlines import (
    DEFAULT_HEADLINES_TOP_N,
    DEFAULT_SUMMARY_MAX_CHARS,
    HEADLINES_ALLOWED_SOURCES,
    format_summary,
    select_todays_headlines,
)

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


def _make_article(
    url: str,
    *,
    source: str = "BBC Business（本紙第1面で稼働中）",
    score: float | None = 50.0,
    description: str = "デフォルト description 100 字未満のサンプル文",
) -> dict:
    return {
        "url": url,
        "title": f"title for {url}",
        "source_name": source,
        "final_score": score,
        "description": description,
    }


# ---------------------------------------------------------------------------
# (a) excluded_urls 除外
# ---------------------------------------------------------------------------

def test_excluded_page1():
    candidates = [
        _make_article("https://a/1", score=90),
        _make_article("https://a/2", score=80),
    ]
    page1_selected = [{"url": "https://a/1"}]
    result = select_todays_headlines(
        target_date=date(2026, 5, 19),
        candidates_scored=candidates,
        page1_selected=page1_selected,
    )
    _check(
        "a1 Page I 採用 URL を除外",
        len(result) == 1 and result[0]["url"] == "https://a/2",
        f"got {[r['url'] for r in result]}",
    )


def test_excluded_page3_dataclass():
    @dataclass
    class _RegSel:
        article: dict | None
    candidates = [
        _make_article("https://a/1", score=90),
        _make_article("https://a/2", score=80),
    ]
    page3 = {
        "R1": _RegSel(article={"url": "https://a/1"}),
        "R2": _RegSel(article=None),
    }
    result = select_todays_headlines(
        target_date=date(2026, 5, 19),
        candidates_scored=candidates,
        page3_selections=page3,
    )
    _check(
        "a2 Page III 採用 URL (dataclass) を除外",
        len(result) == 1 and result[0]["url"] == "https://a/2",
        f"got {[r['url'] for r in result]}",
    )


def test_excluded_page3_dict():
    candidates = [_make_article("https://a/1", score=90),
                  _make_article("https://a/2", score=80)]
    page3 = {"R1": {"article": {"url": "https://a/1"}}}
    result = select_todays_headlines(
        target_date=date(2026, 5, 19),
        candidates_scored=candidates,
        page3_selections=page3,
    )
    _check(
        "a3 Page III 採用 URL (dict 形式) を除外",
        len(result) == 1 and result[0]["url"] == "https://a/2",
    )


# ---------------------------------------------------------------------------
# (b) eligible_sources フィルタ
# ---------------------------------------------------------------------------

def test_source_filter_allowed():
    candidates = [
        _make_article("https://nhk/", source="NHK ニュース 主要"),
        _make_article("https://bbc/", source="BBC Business（本紙第1面で稼働中）"),
        _make_article("https://other/", source="Forbes Japan（リーダーシップ・組織論）"),
        _make_article("https://music/", source="natalie.mu"),
    ]
    result = select_todays_headlines(
        target_date=date(2026, 5, 19),
        candidates_scored=candidates,
    )
    urls = {r["url"] for r in result}
    _check(
        "b1 許可ソースのみ（NHK + BBC）が選定、Forbes/music は除外",
        urls == {"https://nhk/", "https://bbc/"},
        f"got {urls}",
    )


def test_source_filter_custom():
    candidates = [
        _make_article("https://x/", source="X"),
        _make_article("https://y/", source="Y"),
    ]
    result = select_todays_headlines(
        target_date=date(2026, 5, 19),
        candidates_scored=candidates,
        eligible_sources=("X",),
    )
    _check(
        "b2 custom eligible_sources=('X',) で X のみ採用",
        len(result) == 1 and result[0]["source_name"] == "X",
    )


# ---------------------------------------------------------------------------
# (c) final_score 降順 + top_n
# ---------------------------------------------------------------------------

def test_score_descending_and_top_n():
    candidates = [
        _make_article(f"https://x/{i}", score=100 - i,
                      source="NHK ニュース 主要")
        for i in range(10)
    ]
    result = select_todays_headlines(
        target_date=date(2026, 5, 19),
        candidates_scored=candidates,
        top_n=3,
    )
    urls = [r["url"] for r in result]
    _check(
        "c1 top_n=3 で score 降順 (100,99,98)",
        urls == ["https://x/0", "https://x/1", "https://x/2"],
        f"got {urls}",
    )


def test_top_n_default():
    _check(
        "c2 DEFAULT_HEADLINES_TOP_N == 3",
        DEFAULT_HEADLINES_TOP_N == 3,
    )


# ---------------------------------------------------------------------------
# (d) format_summary
# ---------------------------------------------------------------------------

def test_summary_short_passthrough():
    art = {"description": "短い description サンプル文"}
    s = format_summary(art)
    _check(
        "d1 200 字以内はそのまま返す（Sprint 7 微調整 100→200）",
        s == "短い description サンプル文",
        f"got {s!r}",
    )


def test_summary_long_truncate():
    art = {"description": "あ" * 400}
    s = format_summary(art)
    _check(
        "d2 200 字超は末尾「…」付き truncate（Sprint 7 微調整）",
        len(s) == 200 and s.endswith("…"),
        f"got len={len(s)}, ends={s[-3:]!r}",
    )


def test_summary_empty_description():
    """Yahoo! 等の title-only feed 用：description 空なら空文字列."""
    _check(
        "d3 description 欠落 → 空文字列",
        format_summary({}) == "",
    )
    _check(
        "d4 description=None → 空文字列",
        format_summary({"description": None}) == "",
    )
    _check(
        "d5 description=空白のみ → 空文字列",
        format_summary({"description": "   \n  "}) == "",
    )


def test_summary_default_max_chars():
    _check(
        "d6 DEFAULT_SUMMARY_MAX_CHARS == 200 (Sprint 7 微調整、5/19 神山さん観察)",
        DEFAULT_SUMMARY_MAX_CHARS == 200,
    )


def test_summary_custom_max_chars():
    art = {"description": "1234567890"}
    _check(
        "d7 max_chars=5 で truncate（末尾「…」、4 文字本文）",
        format_summary(art, max_chars=5) == "1234…",
        f"got {format_summary(art, max_chars=5)!r}",
    )


# ---------------------------------------------------------------------------
# (e) candidates_scored 空 → 空リスト
# ---------------------------------------------------------------------------

def test_empty_candidates():
    _check(
        "e1 candidates_scored 空 → 空リスト",
        select_todays_headlines(
            target_date=date(2026, 5, 19),
            candidates_scored=[],
        ) == [],
    )


# ---------------------------------------------------------------------------
# (f) 全候補 excluded → 空リスト
# ---------------------------------------------------------------------------

def test_all_excluded():
    candidates = [
        _make_article("https://a/1", source="NHK ニュース 主要"),
        _make_article("https://a/2", source="NHK ニュース 主要"),
    ]
    page1 = [{"url": "https://a/1"}, {"url": "https://a/2"}]
    _check(
        "f1 全候補が Page I 採用済み → 空リスト",
        select_todays_headlines(
            target_date=date(2026, 5, 19),
            candidates_scored=candidates,
            page1_selected=page1,
        ) == [],
    )


def test_all_filtered_out_by_source():
    candidates = [
        _make_article("https://x/", source="Music News"),
        _make_article("https://y/", source="Cooking Site"),
    ]
    _check(
        "f2 全候補が許可外 source → 空リスト",
        select_todays_headlines(
            target_date=date(2026, 5, 19),
            candidates_scored=candidates,
        ) == [],
    )


# ---------------------------------------------------------------------------
# (g) HEADLINES_ALLOWED_SOURCES の構成検証
# ---------------------------------------------------------------------------

def test_allowed_sources_contents():
    expected_keys = {
        "NHK ニュース 主要",
        "NHK ニュース 経済",
        "Yahoo! ニュース 経済",
        "BBC Business（本紙第1面で稼働中）",
        "The Economist",
    }
    _check(
        "g1 HEADLINES_ALLOWED_SOURCES 5 件、全 expected 名を含む",
        set(HEADLINES_ALLOWED_SOURCES) == expected_keys,
        f"got {set(HEADLINES_ALLOWED_SOURCES)}",
    )


def test_allowed_sources_match_registry():
    """business.md にこれらの名前で source が登録されていることを確認."""
    from pathlib import Path
    from scripts.selector.source_registry import build_registry
    reg = build_registry(Path("/home/akiok/projects/tribune/sources"))
    missing = [
        name for name in HEADLINES_ALLOWED_SOURCES
        if name not in reg.sources_by_name
    ]
    _check(
        "g2 全 HEADLINES_ALLOWED_SOURCES が SourceRegistry に存在",
        not missing,
        f"missing={missing}" if missing else "all present",
    )


def main() -> int:
    print("Today's Headlines selector tests (Sprint 7 Phase 2 Step 1, 2026-05-19)")
    print()
    print("(a) excluded_urls 除外:")
    test_excluded_page1()
    test_excluded_page3_dataclass()
    test_excluded_page3_dict()
    print()
    print("(b) eligible_sources フィルタ:")
    test_source_filter_allowed()
    test_source_filter_custom()
    print()
    print("(c) final_score 降順 + top_n:")
    test_score_descending_and_top_n()
    test_top_n_default()
    print()
    print("(d) format_summary:")
    test_summary_short_passthrough()
    test_summary_long_truncate()
    test_summary_empty_description()
    test_summary_default_max_chars()
    test_summary_custom_max_chars()
    print()
    print("(e) candidates_scored 空:")
    test_empty_candidates()
    print()
    print("(f) 全候補 excluded / filtered:")
    test_all_excluded()
    test_all_filtered_out_by_source()
    print()
    print("(g) HEADLINES_ALLOWED_SOURCES 検証:")
    test_allowed_sources_contents()
    test_allowed_sources_match_registry()
    print()
    print(f"=== {PASS} passed, {FAIL} failed ===")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
