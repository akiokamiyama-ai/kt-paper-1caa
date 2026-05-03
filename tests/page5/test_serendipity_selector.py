"""Unit tests for scripts/page5/serendipity_selector.py.

Run::

    python3 -m tests.page5.test_serendipity_selector

External dependencies (fetch / Stage 1+2+3 / dedup_filter / source_registry)
are mocked; pure logic only.
"""

from __future__ import annotations

import json
import random
import sys
import tempfile
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

from scripts.page5 import serendipity_selector

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
# (a) pick_target_category — least-shown + tie randomization
# ---------------------------------------------------------------------------

def test_pick_clear_winner():
    counts = Counter({"business": 5, "books": 1, "music": 3, "outdoor": 4})
    rng = random.Random(0)
    chosen, ties = serendipity_selector.pick_target_category(
        counts, rng=rng,
        eligible=("business", "books", "music", "outdoor"),
    )
    # books has count=1, lowest → should be picked
    _check("a1 single minimum picked unambiguously",
           chosen == "books" and ties == ["books"],
           f"chosen={chosen}, ties={ties}")


def test_pick_with_zero_counts_for_missing_categories():
    """Categories absent from counts treated as 0."""
    counts = Counter({"business": 5, "books": 3})
    rng = random.Random(0)
    chosen, ties = serendipity_selector.pick_target_category(
        counts, rng=rng,
        eligible=("business", "books", "music", "outdoor"),
    )
    # music + outdoor both at 0 → tie
    ok = chosen in {"music", "outdoor"} and set(ties) == {"music", "outdoor"}
    _check("a2 missing categories = 0, tie randomized", ok,
           f"chosen={chosen}, ties={ties}")


def test_pick_all_tied_at_zero():
    counts = Counter()
    rng = random.Random(42)
    chosen, ties = serendipity_selector.pick_target_category(
        counts, rng=rng, eligible=("a", "b", "c"),
    )
    _check("a3 all categories at 0 → all in ties",
           set(ties) == {"a", "b", "c"} and chosen in ties)


def test_pick_tie_distribution_random():
    """5 different RNG seeds should give >=2 different choices when tied."""
    counts = Counter({"business": 10})
    eligible = ("books", "music", "outdoor")  # all at 0 → tied
    chosen_set = set()
    for seed in range(20):
        chosen, _ = serendipity_selector.pick_target_category(
            counts, rng=random.Random(seed), eligible=eligible,
        )
        chosen_set.add(chosen)
    _check("a4 tie produces multiple distinct choices across seeds",
           len(chosen_set) >= 2, f"observed: {chosen_set}")


# ---------------------------------------------------------------------------
# (b) select_from_pool — top-N random
# ---------------------------------------------------------------------------

def _arts(n: int, scores=None) -> list[dict]:
    if scores is None:
        scores = [50.0 - i for i in range(n)]
    return [
        {"url": f"u{i}", "title": f"t{i}", "final_score": scores[i]}
        for i in range(n)
    ]


def test_select_from_pool_random_within_top_n():
    arts = _arts(10)  # scores 50, 49, 48, ..., 41
    chosen_urls = set()
    for seed in range(30):
        c = serendipity_selector.select_from_pool(
            arts, pool_size=5, rng=random.Random(seed),
        )
        chosen_urls.add(c["url"])
    # Should pick from top 5 (u0..u4) only, never from u5..u9
    expected = {f"u{i}" for i in range(5)}
    ok = chosen_urls.issubset(expected) and len(chosen_urls) >= 2
    _check("b1 select_from_pool picks within top-N, with variation", ok,
           f"observed={sorted(chosen_urls)}")


def test_select_from_pool_empty_returns_none():
    _check("b2 empty candidates → None",
           serendipity_selector.select_from_pool([], rng=random.Random(0)) is None)


def test_select_from_pool_smaller_than_n():
    """Only 3 candidates with pool_size=5 → all 3 in pool."""
    arts = _arts(3)
    chosen_urls = set()
    for seed in range(15):
        c = serendipity_selector.select_from_pool(
            arts, pool_size=5, rng=random.Random(seed),
        )
        chosen_urls.add(c["url"])
    _check("b3 pool_size > candidates → uses all available",
           chosen_urls == {"u0", "u1", "u2"},
           f"observed={sorted(chosen_urls)}")


# ---------------------------------------------------------------------------
# (c) _least_shown_categories — pure logic
# ---------------------------------------------------------------------------

def test_least_shown_single_minimum():
    counts = Counter({"a": 5, "b": 1, "c": 3})
    out = serendipity_selector._least_shown_categories(
        counts, eligible=("a", "b", "c"),
    )
    _check("c1 single minimum returned", out == ["b"])


def test_least_shown_multiple_at_zero():
    counts = Counter({"a": 1})
    out = serendipity_selector._least_shown_categories(
        counts, eligible=("a", "b", "c"),
    )
    _check("c2 missing keys = 0, tied at minimum", set(out) == {"b", "c"})


# ---------------------------------------------------------------------------
# (d) History persistence (load/save roundtrip)
# ---------------------------------------------------------------------------

def test_history_save_load_roundtrip():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "page6_history.json"
        entry = {
            "displayed_on": "2026-05-03",
            "article_url": "https://x.test/1",
            "article_title": "Test",
            "article_category": "outdoor",
            "tie_candidates": ["outdoor", "music"],
            "selected_from_pool_size": 5,
            "ai_kamiyama_called": False,
            "ai_kamiyama_failed": False,
            "fallback_used": False,
            "is_placeholder": False,
        }
        serendipity_selector.append_history_entry(entry, path=path)
        loaded = serendipity_selector.load_history(path=path)
    ok = (
        len(loaded["history"]) == 1
        and loaded["history"][0]["article_url"] == "https://x.test/1"
    )
    _check("d1 history append + load roundtrip", ok,
           f"loaded={len(loaded['history'])} entries")


def test_history_load_missing_returns_empty():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "missing.json"
        loaded = serendipity_selector.load_history(path=path)
    _check("d2 missing history file → empty dict",
           loaded == {"history": []})


def test_history_load_corrupt_returns_empty():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "corrupt.json"
        path.write_text("{not valid json")
        loaded = serendipity_selector.load_history(path=path)
    _check("d3 corrupt history → empty dict (no crash)",
           loaded == {"history": []})


# ---------------------------------------------------------------------------
# (e) End-to-end select_for_today (via mocked _fetch_and_score_category)
# ---------------------------------------------------------------------------

def test_select_for_today_zero_candidates_placeholder():
    """When _fetch_and_score returns empty → is_placeholder=True."""
    original = serendipity_selector._fetch_and_score_category
    serendipity_selector._fetch_and_score_category = lambda cat, **kw: ([], 0.0)
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            hpath = Path(tmpdir) / "h.json"
            result = serendipity_selector.select_for_today(
                target_date=date(2026, 5, 3),
                rng=random.Random(0),
                history_path=hpath,
            )
            saved = json.loads(hpath.read_text(encoding="utf-8"))
    finally:
        serendipity_selector._fetch_and_score_category = original
    ok = (
        result["is_placeholder"] is True
        and result["article"] is None
        and len(saved["history"]) == 1
        and saved["history"][0]["is_placeholder"] is True
    )
    _check("e1 zero candidates → placeholder + history records placeholder", ok,
           f"is_placeholder={result['is_placeholder']}, history_len={len(saved['history'])}")


def test_select_for_today_normal_path():
    """Normal: fetch returns 5 articles, picks one, records."""
    fake_arts = _arts(5)  # u0..u4 with scores 50..46
    original = serendipity_selector._fetch_and_score_category
    serendipity_selector._fetch_and_score_category = lambda cat, **kw: (fake_arts, 0.05)
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            hpath = Path(tmpdir) / "h.json"
            result = serendipity_selector.select_for_today(
                target_date=date(2026, 5, 3),
                rng=random.Random(0),
                history_path=hpath,
            )
    finally:
        serendipity_selector._fetch_and_score_category = original
    ok = (
        result["is_placeholder"] is False
        and result["article"] is not None
        and result["article"]["url"] in {f"u{i}" for i in range(5)}
        and result["selected_from_pool_size"] == 5
        and result["category"] in serendipity_selector.ELIGIBLE_CATEGORIES
        and result["cost_usd"] == 0.05
    )
    _check("e2 normal path: article picked from top-5 pool, history written", ok,
           f"url={result['article']['url'] if result['article'] else None}, "
           f"category={result['category']}")


# ---------------------------------------------------------------------------
# Test runner
# ---------------------------------------------------------------------------

def main() -> int:
    print("Page 6 — serendipity_selector tests")
    print()
    print("(a) pick_target_category:")
    test_pick_clear_winner()
    test_pick_with_zero_counts_for_missing_categories()
    test_pick_all_tied_at_zero()
    test_pick_tie_distribution_random()
    print()
    print("(b) select_from_pool:")
    test_select_from_pool_random_within_top_n()
    test_select_from_pool_empty_returns_none()
    test_select_from_pool_smaller_than_n()
    print()
    print("(c) _least_shown_categories:")
    test_least_shown_single_minimum()
    test_least_shown_multiple_at_zero()
    print()
    print("(d) History persistence:")
    test_history_save_load_roundtrip()
    test_history_load_missing_returns_empty()
    test_history_load_corrupt_returns_empty()
    print()
    print("(e) select_for_today end-to-end:")
    test_select_for_today_zero_candidates_placeholder()
    test_select_for_today_normal_path()
    print()
    print(f"=== {PASS} passed, {FAIL} failed ===")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
