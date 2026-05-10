"""Unit tests for Page V serendipity bias 修正（Sprint 6 Phase 2）.

5/4-5/10 観察で cooking 4/7、culture 3/7、他 6 種が 0 採用という構造的偏重を
発見した修正：

1. ELIGIBLE_CATEGORIES から cooking + business + geopolitics 除外（5 種運用）
2. _apply_history_penalty で page5 自身の過去採用 category に penalty 加算

Run::

    python3 -m tests.test_page5_serendipity_bias
"""

from __future__ import annotations

import sys
from collections import Counter
from datetime import date

from scripts.page5 import serendipity_selector as page5
from scripts.page5.serendipity_selector import (
    ELIGIBLE_CATEGORIES,
    HISTORY_PENALTY_DAYS,
    HISTORY_PENALTY_PER_USE,
    _apply_history_penalty,
    _least_shown_categories,
    pick_target_category,
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


# ---------------------------------------------------------------------------
# (a) ELIGIBLE_CATEGORIES の thinning
# ---------------------------------------------------------------------------

def test_cooking_excluded():
    _check(
        "a1 cooking が ELIGIBLE_CATEGORIES に含まれない",
        "cooking" not in ELIGIBLE_CATEGORIES,
        f"got {ELIGIBLE_CATEGORIES}",
    )


def test_business_geopolitics_excluded():
    _check(
        "a2 business が除外",
        "business" not in ELIGIBLE_CATEGORIES,
    )
    _check(
        "a3 geopolitics が除外",
        "geopolitics" not in ELIGIBLE_CATEGORIES,
    )


def test_5_categories_kept():
    expected = {"academic", "books", "culture", "music", "outdoor"}
    actual = set(ELIGIBLE_CATEGORIES)
    _check(
        "a4 5 種運用：academic / books / culture / music / outdoor",
        actual == expected,
        f"expected {expected}, got {actual}",
    )


# ---------------------------------------------------------------------------
# (b) _apply_history_penalty の挙動
# ---------------------------------------------------------------------------

def test_penalty_no_history():
    """history が空なら counts は変わらない."""
    counts = Counter({"culture": 5, "academic": 30})
    result = _apply_history_penalty(counts, [], date(2026, 5, 10))
    _check(
        "b1 空 history なら count 不変",
        result == counts,
        f"got {dict(result)}",
    )


def test_penalty_one_recent_use():
    """過去 7 日に 1 回採用 → +50 加算."""
    counts = Counter({"culture": 5, "academic": 30})
    history = [
        {"displayed_on": "2026-05-09", "article_category": "culture"},
    ]
    result = _apply_history_penalty(counts, history, date(2026, 5, 10))
    _check(
        "b2 1 回採用で +50 加算",
        result["culture"] == 55,
        f"got culture={result['culture']}",
    )


def test_penalty_multiple_uses():
    """過去 7 日に 3 回採用 → +150 加算."""
    counts = Counter({"culture": 5, "academic": 30})
    history = [
        {"displayed_on": "2026-05-04", "article_category": "culture"},
        {"displayed_on": "2026-05-06", "article_category": "culture"},
        {"displayed_on": "2026-05-08", "article_category": "culture"},
    ]
    result = _apply_history_penalty(counts, history, date(2026, 5, 10))
    _check(
        "b3 3 回採用で +150 加算（倍々）",
        result["culture"] == 5 + 50 * 3,
        f"got culture={result['culture']}",
    )


def test_penalty_outside_window():
    """7 日より前の採用は penalty 対象外."""
    counts = Counter({"culture": 5})
    history = [
        # today=2026-05-10, cutoff=2026-05-03
        {"displayed_on": "2026-05-02", "article_category": "culture"},
        # 5/3 (cutoff) は対象に含む（>= cutoff）
        {"displayed_on": "2026-05-03", "article_category": "music"},
    ]
    result = _apply_history_penalty(counts, history, date(2026, 5, 10))
    _check(
        "b4 7 日前 (5/2) の採用は対象外",
        result["culture"] == 5,
        f"got culture={result['culture']}",
    )
    _check(
        "b5 cutoff 当日 (5/3) は対象内",
        result["music"] == 50,
        f"got music={result['music']}",
    )


def test_penalty_today_excluded():
    """today 当日の採用は penalty に含めない（select_for_today 中はまだ history に無い想定）."""
    counts = Counter({"culture": 5})
    history = [
        {"displayed_on": "2026-05-10", "article_category": "culture"},
    ]
    result = _apply_history_penalty(counts, history, date(2026, 5, 10))
    _check(
        "b6 today 当日 (5/10) の採用は対象外",
        result["culture"] == 5,
        f"got culture={result['culture']}",
    )


def test_penalty_invalid_date():
    """壊れた displayed_on は無視."""
    counts = Counter({"culture": 5})
    history = [
        {"displayed_on": "not-a-date", "article_category": "culture"},
        {"displayed_on": None, "article_category": "music"},
        {"article_category": "books"},  # displayed_on なし
    ]
    result = _apply_history_penalty(counts, history, date(2026, 5, 10))
    _check(
        "b7 不正 displayed_on は無視 (count 不変)",
        dict(result) == {"culture": 5},
        f"got {dict(result)}",
    )


# ---------------------------------------------------------------------------
# (c) penalty が pick_target_category 経由で偏重を解消する
# ---------------------------------------------------------------------------

def test_penalty_changes_least_shown():
    """過去 7 日 culture 連続採用 → 次回は他 4 種から選ばれる."""
    # 5/4-5/10 推定 counts: culture 5, academic 30, books 30, music 7, outdoor 7
    counts = Counter({
        "culture": 5,
        "academic": 30,
        "books": 30,
        "music": 7,
        "outdoor": 7,
    })
    # 過去 7 日に culture を 3 回採用したシナリオ
    history = [
        {"displayed_on": "2026-05-06", "article_category": "culture"},
        {"displayed_on": "2026-05-08", "article_category": "culture"},
        {"displayed_on": "2026-05-09", "article_category": "culture"},
    ]
    penalized = _apply_history_penalty(counts, history, date(2026, 5, 10))
    least = _least_shown_categories(penalized)
    _check(
        "c1 penalty で culture が最少候補から外れる",
        "culture" not in least,
        f"got least={least}, penalized={dict(penalized)}",
    )
    _check(
        "c2 最少候補は music or outdoor (count=7)",
        set(least) == {"music", "outdoor"},
        f"got least={least}",
    )


def test_penalty_constants_sane():
    """penalty 定数が他 page の category count を上回ることを確認."""
    # 他 page の典型的 category count はせいぜい数十。penalty 50 は十分大きい。
    _check(
        "c3 HISTORY_PENALTY_PER_USE >= 30 (他 page count を超える)",
        HISTORY_PENALTY_PER_USE >= 30,
        f"got {HISTORY_PENALTY_PER_USE}",
    )
    _check(
        "c4 HISTORY_PENALTY_DAYS == 7",
        HISTORY_PENALTY_DAYS == 7,
        f"got {HISTORY_PENALTY_DAYS}",
    )


def main() -> int:
    print("Page V serendipity bias 修正テスト (Sprint 6 Phase 2, 2026-05-10)")
    print()
    print("(a) ELIGIBLE_CATEGORIES の 5 種運用:")
    test_cooking_excluded()
    test_business_geopolitics_excluded()
    test_5_categories_kept()
    print()
    print("(b) _apply_history_penalty の挙動:")
    test_penalty_no_history()
    test_penalty_one_recent_use()
    test_penalty_multiple_uses()
    test_penalty_outside_window()
    test_penalty_today_excluded()
    test_penalty_invalid_date()
    print()
    print("(c) penalty が偏重解消に効く (実 counts シナリオ):")
    test_penalty_changes_least_shown()
    test_penalty_constants_sane()
    print()
    print(f"=== {PASS} passed, {FAIL} failed ===")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
