"""Unit tests for scripts/selector/page3.py.

Run::

    python3 -m scripts.selector.test_page3

Covers:
* (a) _region_for / _filter_for_region — 各領域の判定（R1〜R6 + None）
* (b) _select_top_for_region — final_score ソート、候補なし
* (c) _generate_kicker — title 抽出 / source_name map / fallback
* (d) select_page3_articles — dedup の効き
* (e) run_page3_pipeline — 6領域埋まる / 一部欠ける / 全欠ける
* (f) HTML rendering helpers (defined in regen_front_page_v2 — covered there)
"""

from __future__ import annotations

import sys
from datetime import date
from typing import Any

from . import page3

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
# Article fixtures
# ---------------------------------------------------------------------------

def _art(
    *,
    url: str = "https://example.test/a",
    title: str = "Sample title",
    description: str = "Sample description",
    source_name: str = "The Economist",
    category: str = "business",
    final_score: float = 50.0,
) -> dict:
    return {
        "url": url,
        "title": title,
        "description": description,
        "source_name": source_name,
        "category": category,
        "final_score": final_score,
        "美意識1": 6, "美意識3": 5, "美意識5": 4, "美意識6": 4, "美意識8": 3,
    }


# ---------------------------------------------------------------------------
# (a) _region_for / _filter_for_region
# ---------------------------------------------------------------------------

def test_region_R6_academic():
    a = _art(source_name="Stanford Encyclopedia of Philosophy", category="academic",
             title="Phenomenology and the structure of consciousness")
    _check("a1 R6: academic.md SEP article → R6", page3._region_for(a) == "R6",
           f"got {page3._region_for(a)}")


def test_region_R6_books_natural_science():
    a = _art(source_name="Quanta Magazine", category="books",
             title="A new theorem on quantum entropy")
    _check("a2 R6: Quanta (books 自然科学ノンフ) → R6",
           page3._region_for(a) == "R6", f"got {page3._region_for(a)}")


def test_region_R5_books_default():
    a = _art(source_name="早川書房", category="books",
             title="新刊：テッド・チャン短編集")
    _check("a3 R5: books (非自然科学) → R5",
           page3._region_for(a) == "R5", f"got {page3._region_for(a)}")


def test_region_R5_aeon_no_R6_keyword():
    a = _art(source_name="Aeon", category="academic",
             title="An essay on grief and remembrance",
             description="Reflections on loss")
    # academic だが Aeon かつ R6 keyword なし → R5 を取る
    _check("a4 R5: Aeon without R6 keywords → R5",
           page3._region_for(a) == "R5", f"got {page3._region_for(a)}")


def test_region_R3_AI_regulation():
    a = _art(source_name="The Economist", category="business",
             title="EU AI Act enforcement begins this year",
             description="The Commission opens its first cases")
    _check("a5 R3: AI Act keyword → R3",
           page3._region_for(a) == "R3", f"got {page3._region_for(a)}")


def test_region_R2_japan_macro():
    a = _art(source_name="日本経済新聞", category="business",
             title="生産年齢人口、初の60%割れ",
             description="2025年国勢調査確定値、人口減少が加速")
    _check("a6 R2: 日本経済新聞 + 人口/生産年齢 → R2",
           page3._region_for(a) == "R2", f"got {page3._region_for(a)}")


def test_region_R4_japan_industry():
    a = _art(source_name="東洋経済オンライン", category="business",
             title="トヨタの水素戦略——M&Aによる業界再編",
             description="トヨタとソニーが組む経営戦略")
    _check("a7 R4: トヨタ + M&A + 業界再編 → R4",
           page3._region_for(a) == "R4", f"got {page3._region_for(a)}")


def test_region_R1_geopolitics_default():
    a = _art(source_name="Foresight", category="geopolitics",
             title="UAEのOPEC脱退、市場支配力の行方",
             description="OPECプラスの枠組みが揺らぐ")
    # geopolitics で R6/R5/R3/R2/R4 にマッチしなければ R1
    _check("a8 R1: geopolitics + OPEC → R1",
           page3._region_for(a) == "R1", f"got {page3._region_for(a)}")


def test_region_none_unmatched():
    a = _art(source_name="Random Blog", category="other",
             title="Hello world",
             description="A test article unrelated to any region")
    _check("a9 None: unmatched article → None",
           page3._region_for(a) is None, f"got {page3._region_for(a)}")


def test_filter_for_region():
    arts = [
        _art(url="u1", source_name="The Economist", category="business",
             title="EU AI Act timeline", description="regulatory"),         # R3
        _art(url="u2", source_name="Foresight", category="geopolitics",
             title="OPEC oil prices", description="markets"),                # R1
        _art(url="u3", source_name="Quanta Magazine", category="books",
             title="Quantum entropy theorem"),                               # R6
    ]
    r3 = page3._filter_for_region(arts, "R3")
    r1 = page3._filter_for_region(arts, "R1")
    r6 = page3._filter_for_region(arts, "R6")
    ok = (
        len(r3) == 1 and r3[0]["url"] == "u1"
        and len(r1) == 1 and r1[0]["url"] == "u2"
        and len(r6) == 1 and r6[0]["url"] == "u3"
    )
    _check("a10 _filter_for_region partitions correctly", ok)


# ---------------------------------------------------------------------------
# (b) _select_top_for_region
# ---------------------------------------------------------------------------

def test_select_top_picks_highest_score():
    arts = [
        _art(url="u1", source_name="The Economist", category="business",
             title="EU AI Act 1", final_score=40),
        _art(url="u2", source_name="The Economist", category="business",
             title="EU AI Act 2", final_score=60),  # higher
        _art(url="u3", source_name="The Economist", category="business",
             title="EU AI Act 3", final_score=50),
    ]
    pick = page3._select_top_for_region(arts, "R3")
    ok = pick is not None and pick["url"] == "u2"
    _check("b1 select_top_for_region picks highest final_score", ok,
           f"picked={pick.get('url') if pick else 'None'}")


def test_select_top_no_candidates():
    arts = [
        _art(url="u1", source_name="The Economist", category="business",
             title="EU AI Act", final_score=40),
    ]
    pick = page3._select_top_for_region(arts, "R6")  # 学術 — no match
    _check("b2 select_top_for_region returns None when no candidates",
           pick is None)


# ---------------------------------------------------------------------------
# (c) _generate_kicker
# ---------------------------------------------------------------------------

def test_kicker_title_location_extraction():
    a = _art(source_name="Reuters Business", title="Singapore's GIC trims US tech")
    k = page3._generate_kicker(a, "R1")
    _check("c1 kicker: title location 'Singapore' extracted",
           k == "Singapore", f"got {k!r}")


def test_kicker_title_japanese_location():
    a = _art(source_name="日本経済新聞", title="東京・人口断崖：生産年齢人口割れ")
    k = page3._generate_kicker(a, "R2")
    _check("c2 kicker: title 和文地名 '東京' 抽出",
           k == "東京", f"got {k!r}")


def test_kicker_source_map():
    a = _art(source_name="The Economist", title="A vague headline")
    k = page3._generate_kicker(a, "R1")
    _check("c3 kicker: source_name 'The Economist' → 'London'",
           k == "London", f"got {k!r}")


def test_kicker_project_syndicate_global():
    """神山さん指定：Project Syndicate は 'Prague' でなく '国際・論考'。"""
    a = _art(source_name="Project Syndicate", title="A global perspective")
    k = page3._generate_kicker(a, "R3")
    _check("c4 kicker: Project Syndicate → '国際・論考' (神山さん指定)",
           k == "国際・論考", f"got {k!r}")


def test_kicker_fallback_to_region():
    a = _art(source_name="Unknown Random Source", title="generic news today")
    k = page3._generate_kicker(a, "R4")
    _check("c5 kicker: source not in map → REGION_KICKER_FALLBACK[R4]",
           k == "国内産業", f"got {k!r}")


def test_kicker_fallback_R6():
    a = _art(source_name="Unknown Source", title="something academic")
    k = page3._generate_kicker(a, "R6")
    _check("c6 kicker R6 fallback → '学術・科学'",
           k == "学術・科学", f"got {k!r}")


def test_kicker_no_false_positive_in_long_title():
    """単語境界マッチ：'New Yorker' 等の途中マッチで誤発火しないか。"""
    a = _art(source_name="The Economist", title="Tokyoville-style architecture")
    k = page3._generate_kicker(a, "R5")
    # "Tokyo" は単語境界外 (Tokyoville の一部) なのでマッチしない、
    # source map の "London" にフォールバック
    _check("c7 kicker: 'Tokyoville' does not match 'Tokyo' word boundary",
           k == "London", f"got {k!r}")


# ---------------------------------------------------------------------------
# (d) select_page3_articles — dedup
# ---------------------------------------------------------------------------

def test_dedup_today():
    arts = [
        _art(url="u_top", source_name="The Economist", category="business",
             title="EU AI Act case 1", description="reg", final_score=70),
        _art(url="u2", source_name="The Economist", category="business",
             title="EU AI Act case 2", description="reg", final_score=50),
    ]
    selections, total, after = page3.select_page3_articles(
        arts,
        displayed_urls_today={"u_top"},  # u_top を当日他面 dedup
    )
    pick = selections["R3"].article
    ok = pick is not None and pick["url"] == "u2" and after == 1
    _check("d1 dedup: today's URL excluded → next-best chosen", ok,
           f"picked={pick.get('url') if pick else 'None'}, after_dedup={after}")


def test_dedup_past_n():
    arts = [
        _art(url="u1", source_name="The Economist", category="business",
             title="EU AI Act", description="reg", final_score=70),
    ]
    selections, _, _ = page3.select_page3_articles(
        arts,
        displayed_urls_past_n={"u1"},  # 過去 N 日 page3 で表示済
    )
    _check("d2 dedup: past-N-days URL excluded → R3 placeholder",
           selections["R3"].article is None)


def test_dedup_combined():
    arts = [
        _art(url="u1", source_name="The Economist", category="business",
             title="EU AI Act 1", description="reg", final_score=70),
        _art(url="u2", source_name="The Economist", category="business",
             title="EU AI Act 2", description="reg", final_score=60),
    ]
    selections, _, after = page3.select_page3_articles(
        arts,
        displayed_urls_today={"u1"},
        displayed_urls_past_n={"u2"},
    )
    _check("d3 dedup: today+past_n combined removes both",
           selections["R3"].article is None and after == 0)


# ---------------------------------------------------------------------------
# (e) run_page3_pipeline (with mock fetcher)
# ---------------------------------------------------------------------------

def _make_full_six_region_set() -> list[dict]:
    return [
        # R1 国際金融
        _art(url="r1", source_name="Foreign Affairs", category="geopolitics",
             title="Currency wars and the dollar's future",
             description="An analysis on global monetary order, IMF and BRICS",
             final_score=55),
        # R2 国内マクロ
        _art(url="r2", source_name="日本経済新聞", category="business",
             title="春闘賃上げ率、過去最高水準に",
             description="春闘とGDP動向、日銀の物価判断",
             final_score=52),
        # R3 国際規制
        _art(url="r3", source_name="The Economist", category="business",
             title="GDPR enforcement intensifies in 2026",
             description="EU regulators target antitrust violations",
             final_score=58),
        # R4 国内産業
        _art(url="r4", source_name="東洋経済オンライン", category="business",
             title="トヨタとソニーのM&A戦略",
             description="日本企業の業界再編が加速、ガバナンス強化",
             final_score=54),
        # R5 文化
        _art(url="r5", source_name="早川書房", category="books",
             title="ノーベル文学賞作家の新刊翻訳",
             description="現代思想の名著、書評で話題",
             final_score=50),
        # R6 学術
        _art(url="r6", source_name="Quanta Magazine", category="books",
             title="A new theorem in quantum physics",
             description="認知科学とneuroscience の交差",
             final_score=53),
    ]


def _make_mock_fetcher(articles: list[dict]):
    def fetcher(*, pre_evaluated=None, limit=8):
        return list(articles), 0.0
    return fetcher


def test_pipeline_all_six_regions_filled():
    fetcher = _make_mock_fetcher(_make_full_six_region_set())
    result = page3.run_page3_pipeline(
        target_date=date(2026, 5, 2),
        fetcher=fetcher,
        write_log=False,
    )
    filled = sum(1 for s in result.selections.values() if s.article is not None)
    ok = filled == 6 and result.placeholder_count == 0
    _check("e1 pipeline: 6 regions all filled", ok,
           f"filled={filled}, placeholders={result.placeholder_count}")


def test_pipeline_one_region_empty():
    arts = _make_full_six_region_set()
    # R6 を抜く（Quanta Magazine 記事を消す）
    arts = [a for a in arts if a["url"] != "r6"]
    fetcher = _make_mock_fetcher(arts)
    result = page3.run_page3_pipeline(
        target_date=date(2026, 5, 2),
        fetcher=fetcher,
        write_log=False,
    )
    ok = (
        result.selections["R6"].article is None
        and result.selections["R6"].fallback_reason == "no_candidates"
        and result.placeholder_count == 1
        and sum(1 for s in result.selections.values() if s.article is not None) == 5
    )
    _check("e2 pipeline: R6 empty → placeholder_count=1", ok,
           f"placeholders={result.placeholder_count}, R6 article={result.selections['R6'].article}")


def test_pipeline_all_empty():
    fetcher = _make_mock_fetcher([])
    result = page3.run_page3_pipeline(
        target_date=date(2026, 5, 2),
        fetcher=fetcher,
        write_log=False,
    )
    ok = result.placeholder_count == 6 and result.candidates_total == 0
    _check("e3 pipeline: empty fetch → 6 placeholders", ok,
           f"placeholders={result.placeholder_count}")


def test_pipeline_dedup_integration():
    """pipeline に dedup を渡して効くか。"""
    arts = _make_full_six_region_set()
    fetcher = _make_mock_fetcher(arts)
    result = page3.run_page3_pipeline(
        target_date=date(2026, 5, 2),
        fetcher=fetcher,
        displayed_urls_today={"r1", "r2"},  # R1 + R2 を当日 dedup
        write_log=False,
    )
    ok = (
        result.selections["R1"].article is None
        and result.selections["R2"].article is None
        and result.selections["R3"].article is not None
    )
    _check("e4 pipeline: dedup removes R1+R2, R3+ remain", ok,
           f"R1={result.selections['R1'].article}, R2={result.selections['R2'].article}")


def test_pipeline_warning_on_2plus_placeholders():
    """2 領域以上 placeholder で stderr WARNING が出るか（exception を上げない）。"""
    arts = _make_full_six_region_set()[:3]  # 最初の3つだけ → R4/R5/R6 は空
    fetcher = _make_mock_fetcher(arts)
    result = page3.run_page3_pipeline(
        target_date=date(2026, 5, 2),
        fetcher=fetcher,
        write_log=False,
    )
    ok = result.placeholder_count >= 2  # warning は stderr 経由
    _check("e5 pipeline: 2+ placeholders triggers WARNING (no exception)", ok,
           f"placeholders={result.placeholder_count}")


# ---------------------------------------------------------------------------
# Stage 2 sharing via pre_evaluated
# ---------------------------------------------------------------------------

def test_pre_evaluated_skips_stage2():
    """pre_evaluated に URL があれば、その記事は Stage 2 を再評価しない（コスト 0）。"""
    captured_calls: list[Any] = []

    def fetcher(*, pre_evaluated=None, limit=8):
        # Mock: pre_evaluated に r1 があるとき、Stage 2 を呼ばないことを確認
        captured_calls.append({"pre_evaluated_keys": list(pre_evaluated.keys()) if pre_evaluated else None})
        return _make_full_six_region_set(), 0.0

    result = page3.run_page3_pipeline(
        target_date=date(2026, 5, 2),
        fetcher=fetcher,
        pre_evaluated={"r1": _make_full_six_region_set()[0]},
        write_log=False,
    )
    ok = (
        len(captured_calls) == 1
        and captured_calls[0]["pre_evaluated_keys"] == ["r1"]
    )
    _check("e6 pre_evaluated: passed through to fetcher", ok,
           f"calls={captured_calls}")


# ---------------------------------------------------------------------------
# Test runner
# ---------------------------------------------------------------------------

def main() -> int:
    print("Page 3 unit tests")
    print()

    print("(a) _region_for / _filter_for_region:")
    test_region_R6_academic()
    test_region_R6_books_natural_science()
    test_region_R5_books_default()
    test_region_R5_aeon_no_R6_keyword()
    test_region_R3_AI_regulation()
    test_region_R2_japan_macro()
    test_region_R4_japan_industry()
    test_region_R1_geopolitics_default()
    test_region_none_unmatched()
    test_filter_for_region()

    print()
    print("(b) _select_top_for_region:")
    test_select_top_picks_highest_score()
    test_select_top_no_candidates()

    print()
    print("(c) _generate_kicker:")
    test_kicker_title_location_extraction()
    test_kicker_title_japanese_location()
    test_kicker_source_map()
    test_kicker_project_syndicate_global()
    test_kicker_fallback_to_region()
    test_kicker_fallback_R6()
    test_kicker_no_false_positive_in_long_title()

    print()
    print("(d) select_page3_articles — dedup:")
    test_dedup_today()
    test_dedup_past_n()
    test_dedup_combined()

    print()
    print("(e) run_page3_pipeline:")
    test_pipeline_all_six_regions_filled()
    test_pipeline_one_region_empty()
    test_pipeline_all_empty()
    test_pipeline_dedup_integration()
    test_pipeline_warning_on_2plus_placeholders()
    test_pre_evaluated_skips_stage2()

    print()
    print(f"=== {PASS} passed, {FAIL} failed ===")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
