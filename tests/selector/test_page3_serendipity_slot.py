"""Page III セレンディピティ枠のテスト (C155, Sprint 13, 2026-08-10).

旧第5面上段「今朝出会った1本」を第3面 6 枠目に移設した際の挙動を固定する。

Tests:
  a) スロット構成（R2 廃止 / SER 追加 / 表示順）
  b) _select_serendipity_slot: 正常系 / placeholder / 例外 / 3面内重複
  c) cost の加算
  d) kicker は常に「今朝の一本」
  e) runner_up_candidates の抽出

Run::

    python3 -m tests.selector.test_page3_serendipity_slot
"""

from __future__ import annotations

import sys
from datetime import date

from scripts.selector import page3

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


def _art(url: str, **kw) -> dict:
    a = {
        "url": url,
        "title": "sample",
        "source_name": "Pitchfork",
        "description": "desc",
        "final_score": 50,
        "category": "music",
    }
    a.update(kw)
    return a


def _result() -> page3.Page3Result:
    return page3.Page3Result(today=date(2026, 8, 16))


# ---------------------------------------------------------------------------
# (a) スロット構成
# ---------------------------------------------------------------------------

def test_regions_exclude_r2():
    _check("a1 REGIONS は 5 領域で R2 を含まない",
           page3.REGIONS == ("R1", "R3", "R4", "R5", "R6"), f"got {page3.REGIONS}")


def test_detection_order_excludes_r2():
    _check("a2 判定順序も R2 を含まない（R6→R5→R3→R4→R1）",
           page3.REGION_DETECTION_ORDER == ("R6", "R5", "R3", "R4", "R1"),
           f"got {page3.REGION_DETECTION_ORDER}")


def test_display_slots_end_with_serendipity():
    _check("a3 DISPLAY_SLOTS は 6 枠、最後が SER",
           page3.DISPLAY_SLOTS == ("R1", "R3", "R4", "R5", "R6", "SER"),
           f"got {page3.DISPLAY_SLOTS}")


def test_serendipity_has_display_metadata():
    _check("a4 SER に表示名がある",
           page3.REGION_DISPLAY_NAMES.get("SER") == "セレンディピティ")
    _check("a5 SER に kicker fallback がある",
           page3.REGION_KICKER_FALLBACK.get("SER") == "今朝の一本")


def test_r2_matcher_removed():
    _check("a6 _REGION_MATCHERS に R2 が無い",
           "R2" not in page3._REGION_MATCHERS,
           f"got {sorted(page3._REGION_MATCHERS)}")
    _check("a7 _matches_R2 関数自体が削除されている",
           not hasattr(page3, "_matches_R2"))


# ---------------------------------------------------------------------------
# (b) _select_serendipity_slot
# ---------------------------------------------------------------------------

def test_slot_happy_path():
    res = _result()
    sel = page3._select_serendipity_slot(
        target_date=date(2026, 8, 16),
        selector=lambda **kw: {
            "article": _art("https://ser/1"), "category": "music",
            "is_placeholder": False, "cost_usd": 0.02,
        },
        exclude_urls=set(),
        result=res,
    )
    _check("b1 記事が SER スロットに入る",
           sel.article is not None and sel.article["url"] == "https://ser/1")
    _check("b2 region ラベルは SER", sel.region == "SER")
    _check("b3 fallback_reason は None", sel.fallback_reason is None)
    _check("b4 final_score が引き継がれる", sel.final_score == 50)


def test_slot_placeholder_when_no_candidates():
    res = _result()
    sel = page3._select_serendipity_slot(
        target_date=date(2026, 8, 16),
        selector=lambda **kw: {
            "article": None, "category": "music",
            "is_placeholder": True, "cost_usd": 0.0,
        },
        exclude_urls=set(),
        result=res,
    )
    _check("b5 候補ゼロ → placeholder",
           sel.article is None and sel.fallback_reason == "serendipity_no_candidates",
           f"got {sel.fallback_reason}")


def test_slot_survives_selector_exception():
    """セレンディピティが落ちても 3 面全体は落とさない（1 枠の欠損に留める）."""
    res = _result()

    def boom(**kw):
        raise RuntimeError("fetch exploded")

    sel = page3._select_serendipity_slot(
        target_date=date(2026, 8, 16),
        selector=boom,
        exclude_urls=set(),
        result=res,
    )
    _check("b6 例外は握り潰して placeholder に倒す",
           sel.article is None
           and sel.fallback_reason == "serendipity_error: RuntimeError",
           f"got {sel.fallback_reason}")


def test_slot_rejects_duplicate_within_page3():
    """5 領域で既に採用済の URL が来たら 1 枠空ける（3 面内の二重掲載防止）."""
    res = _result()
    sel = page3._select_serendipity_slot(
        target_date=date(2026, 8, 16),
        selector=lambda **kw: {
            "article": _art("https://dup/"), "category": "books",
            "is_placeholder": False, "cost_usd": 0.0,
        },
        exclude_urls={"https://dup/"},
        result=res,
    )
    _check("b7 3 面内で重複する URL は placeholder に倒す",
           sel.article is None
           and sel.fallback_reason == "serendipity_duplicate_within_page3",
           f"got {sel.fallback_reason}")


def test_slot_sets_category_when_missing():
    res = _result()
    art = _art("https://ser/2")
    del art["category"]
    sel = page3._select_serendipity_slot(
        target_date=date(2026, 8, 16),
        selector=lambda **kw: {
            "article": art, "category": "outdoor",
            "is_placeholder": False, "cost_usd": 0.0,
        },
        exclude_urls=set(),
        result=res,
    )
    _check("b8 category 欠落時は selector の category を載せる",
           sel.article.get("category") == "outdoor", f"got {sel.article.get('category')}")


# ---------------------------------------------------------------------------
# (c) cost 加算
# ---------------------------------------------------------------------------

def test_slot_adds_cost_to_result():
    res = _result()
    res.cost_usd = 0.10
    page3._select_serendipity_slot(
        target_date=date(2026, 8, 16),
        selector=lambda **kw: {
            "article": _art("https://ser/3"), "category": "music",
            "is_placeholder": False, "cost_usd": 0.025,
        },
        exclude_urls=set(),
        result=res,
    )
    _check("c1 serendipity の cost が Page3Result に加算される",
           abs(res.cost_usd - 0.125) < 1e-9, f"got {res.cost_usd}")


def test_slot_cost_is_zero_safe_on_exception():
    res = _result()
    res.cost_usd = 0.10

    def boom(**kw):
        raise ValueError("x")

    page3._select_serendipity_slot(
        target_date=date(2026, 8, 16), selector=boom,
        exclude_urls=set(), result=res,
    )
    _check("c2 例外時は cost を増やさない",
           abs(res.cost_usd - 0.10) < 1e-9, f"got {res.cost_usd}")


# ---------------------------------------------------------------------------
# (d) kicker
# ---------------------------------------------------------------------------

def test_serendipity_kicker_is_fixed():
    """地名 / source map を経由せず常に「今朝の一本」."""
    a = _art("https://x/", source_name="The Economist", title="Tokyo rally deepens")
    k = page3._generate_kicker(a, "SER")
    _check("d1 SER の kicker は地名/source map を無視して固定",
           k == "今朝の一本", f"got {k!r}")


def test_region_kicker_still_uses_location():
    """通常領域は従来通り地名抽出が効く（SER の特別扱いが漏れていない）."""
    a = _art("https://y/", source_name="The Economist", title="Tokyo rally deepens")
    k = page3._generate_kicker(a, "R1")
    _check("d2 通常領域は地名抽出が効く", k == "Tokyo", f"got {k!r}")


# ---------------------------------------------------------------------------
# (e) runner_up_candidates
# ---------------------------------------------------------------------------

def _fetcher(articles):
    def f(*, pre_evaluated=None, limit=8):
        return list(articles), 0.0
    return f


def test_runner_ups_exclude_selected_and_deduped():
    arts = [
        _art("https://r6/", source_name="Quanta Magazine", category="academic",
             title="A new proof reshapes number theory", final_score=90),
        _art("https://ru/1", final_score=80),
        _art("https://ru/2", final_score=70),
        _art("https://skip/", final_score=60),
    ]
    result = page3.run_page3_pipeline(
        target_date=date(2026, 8, 16),
        fetcher=_fetcher(arts),
        displayed_urls_today={"https://skip/"},
        write_log=False,
        serendipity_selector=lambda **kw: {
            "article": None, "category": "music",
            "is_placeholder": True, "cost_usd": 0.0,
        },
    )
    ru_urls = [a["url"] for a in result.runner_up_candidates]
    used = {
        s.article["url"] for s in result.selections.values() if s.article
    }
    _check("e1 runner-up に採用済 URL が含まれない",
           not (set(ru_urls) & used), f"ru={ru_urls}, used={used}")
    _check("e2 runner-up に dedup 済 URL が含まれない",
           "https://skip/" not in ru_urls, f"ru={ru_urls}")
    _check("e3 runner-up は final_score 降順",
           ru_urls == sorted(ru_urls,
                             key=lambda u: -next(a["final_score"] for a in arts if a["url"] == u)),
           f"got {ru_urls}")


def test_runner_ups_capped():
    arts = [_art(f"https://ru/{i}", final_score=100 - i) for i in range(40)]
    result = page3.run_page3_pipeline(
        target_date=date(2026, 8, 16),
        fetcher=_fetcher(arts),
        write_log=False,
        serendipity_selector=lambda **kw: {
            "article": None, "category": "music",
            "is_placeholder": True, "cost_usd": 0.0,
        },
    )
    _check("e4 runner-up は RUNNER_UP_POOL_SIZE で打ち切る",
           len(result.runner_up_candidates) <= page3.RUNNER_UP_POOL_SIZE,
           f"got {len(result.runner_up_candidates)}")


def main() -> int:
    print("Page III セレンディピティ枠 tests (C155, Sprint 13, 2026-08-10)")
    print()
    print("(a) スロット構成:")
    test_regions_exclude_r2()
    test_detection_order_excludes_r2()
    test_display_slots_end_with_serendipity()
    test_serendipity_has_display_metadata()
    test_r2_matcher_removed()
    print()
    print("(b) _select_serendipity_slot:")
    test_slot_happy_path()
    test_slot_placeholder_when_no_candidates()
    test_slot_survives_selector_exception()
    test_slot_rejects_duplicate_within_page3()
    test_slot_sets_category_when_missing()
    print()
    print("(c) cost 加算:")
    test_slot_adds_cost_to_result()
    test_slot_cost_is_zero_safe_on_exception()
    print()
    print("(d) kicker:")
    test_serendipity_kicker_is_fixed()
    test_region_kicker_still_uses_location()
    print()
    print("(e) runner_up_candidates:")
    test_runner_ups_exclude_selected_and_deduped()
    test_runner_ups_capped()
    print()
    print(f"=== {PASS} passed, {FAIL} failed ===")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
