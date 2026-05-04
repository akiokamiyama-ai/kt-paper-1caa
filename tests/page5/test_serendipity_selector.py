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
# (f) Culture category integration (added 2026-05-03)
# ---------------------------------------------------------------------------

def test_culture_in_eligible_categories():
    _check("f1 'culture' is in ELIGIBLE_CATEGORIES",
           "culture" in serendipity_selector.ELIGIBLE_CATEGORIES,
           f"ELIGIBLE_CATEGORIES={serendipity_selector.ELIGIBLE_CATEGORIES}")


def test_culture_pickable_when_least_shown():
    """culture が単独で最少表示なら必ず選ばれる。"""
    counts = Counter({
        "business": 5, "geopolitics": 4, "academic": 6,
        "books": 3, "music": 4, "outdoor": 3, "cooking": 2,
        "culture": 0,
    })
    rng = random.Random(0)
    chosen, ties = serendipity_selector.pick_target_category(counts, rng=rng)
    _check("f2 culture が単独最少なら必ず選ばれる",
           chosen == "culture" and ties == ["culture"],
           f"chosen={chosen}, ties={ties}")


def test_culture_participates_in_tie_random():
    """全カテゴリが count=0 の初日想定で、culture が選ばれる seed が存在する。"""
    counts = Counter()  # 全 category で 0 → 8-way tie
    chosen_set = set()
    for seed in range(50):
        chosen, ties = serendipity_selector.pick_target_category(
            counts, rng=random.Random(seed),
        )
        chosen_set.add(chosen)
        # ties に culture が含まれる
        assert "culture" in ties, f"seed={seed}: culture missing from ties={ties}"
    _check("f3 culture は tie に含まれ、seed を変えれば実際に選ばれる",
           "culture" in chosen_set,
           f"50 seeds で観測された choice 集合={sorted(chosen_set)}")


# ---------------------------------------------------------------------------
# (g) B1 改修：Reference priority も fetch 対象に含む（2026-05-03）
# ---------------------------------------------------------------------------

def test_fetch_calls_include_reference_priority():
    """_fetch_and_score_category は high/medium/reference の3優先度で fetch_run を呼ぶ。"""
    calls: list[dict] = []

    def fake_fetch_run(*, category, priority, **kw):
        calls.append({"category": category, "priority": priority})
        return {"articles": []}  # 空で OK、本テストは call 引数の検証のみ

    original_fetch = serendipity_selector.fetch_run
    serendipity_selector.fetch_run = fake_fetch_run
    try:
        scored, cost = serendipity_selector._fetch_and_score_category("culture")
    finally:
        serendipity_selector.fetch_run = original_fetch

    priorities = [c["priority"] for c in calls if c["category"] == "culture"]
    ok = (
        set(priorities) == {"high", "medium", "reference"}
        and len(priorities) == 3
        and scored == []
        and cost == 0.0
    )
    _check("g1 fetch_run is called for high+medium+reference (3 calls)", ok,
           f"priorities={priorities}, scored_len={len(scored)}")


def test_reference_articles_reach_pipeline_input():
    """Reference 由来の Article が dedup/pipeline 入力に到達する。

    fetch_run mock で priority="reference" のときだけ Article を返し、その URL が
    Stage 1 の入力（pipeline_dicts）に含まれることを Stage 1 mock で検証する。
    """
    from datetime import datetime
    from scripts.lib.source import Article

    ref_article = Article(
        source_name="Pitchfork",
        title="Reference-only article",
        link="https://pitchfork.test/ref-only-1",
        description="dummy",
        pub_date=datetime(2026, 5, 3, 9, 0, 0),
        body_paragraphs=["dummy body"],
    )

    def fake_fetch_run(*, category, priority, **kw):
        # high/medium は空、reference のときだけ 1 件返す
        if priority == "reference":
            return {"articles": [ref_article]}
        return {"articles": []}

    captured_pipeline_input: list[list[dict]] = []

    def fake_run_stage1(pipeline_dicts):
        captured_pipeline_input.append(list(pipeline_dicts))
        # 全件 surviving 扱い
        return [{**d, "is_excluded": False} for d in pipeline_dicts]

    # Stage 2 が呼ばれないように、stage1 の結果を空にせず、stage2 mock も入れる
    def fake_run_stage2(arts):
        class FakeS2:
            evaluations_by_url = {a["url"]: {"final_score": 50.0} for a in arts}
            cost_usd = 0.0
            errors = []
        return FakeS2()

    original_fetch = serendipity_selector.fetch_run
    original_s1 = serendipity_selector.run_stage1
    original_s2 = serendipity_selector.run_stage2
    serendipity_selector.fetch_run = fake_fetch_run
    serendipity_selector.run_stage1 = fake_run_stage1
    serendipity_selector.run_stage2 = fake_run_stage2
    try:
        scored, _cost = serendipity_selector._fetch_and_score_category("music")
    finally:
        serendipity_selector.fetch_run = original_fetch
        serendipity_selector.run_stage1 = original_s1
        serendipity_selector.run_stage2 = original_s2

    # Stage 1 入力に reference 由来の URL が含まれている
    urls_in_pipeline = {
        d["url"] for batch in captured_pipeline_input for d in batch
    }
    scored_urls = {a.get("url") for a in scored}
    ok = (
        "https://pitchfork.test/ref-only-1" in urls_in_pipeline
        and "https://pitchfork.test/ref-only-1" in scored_urls
    )
    _check("g2 Reference 由来の記事が Stage 1 入力 + 最終 scored に到達する", ok,
           f"pipeline_urls={urls_in_pipeline}, scored_urls={scored_urls}")


# ---------------------------------------------------------------------------
# (h) Sprint 5 task #5: update_history_column_fields (2026-05-04)
# ---------------------------------------------------------------------------

def _seed_history(path: Path, entries: list[dict]) -> None:
    """Helper: seed a history file with given entries."""
    serendipity_selector.save_history({"history": entries}, path=path)


def test_update_history_match_found_returns_true_and_updates():
    """h1: 該当 entry が見つかれば 3 fields を更新、True return。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "h.json"
        _seed_history(path, [
            {
                "displayed_on": "2026-05-04",
                "article_url": "https://x.test/a",
                "article_title": "T",
                "article_category": "culture",
                "tie_candidates": ["culture"],
                "selected_from_pool_size": 5,
                "ai_kamiyama_called": False,
                "ai_kamiyama_failed": False,
                "fallback_used": False,
                "is_placeholder": False,
            },
        ])
        ok = serendipity_selector.update_history_column_fields(
            target_date=date(2026, 5, 4),
            article_url="https://x.test/a",
            ai_kamiyama_called=True,
            ai_kamiyama_failed=False,
            fallback_used=False,
            history_path=path,
        )
        loaded = serendipity_selector.load_history(path=path)
    e = loaded["history"][0]
    _check("h1 match: returns True and updates 3 fields",
           ok is True
           and e["ai_kamiyama_called"] is True
           and e["ai_kamiyama_failed"] is False
           and e["fallback_used"] is False,
           f"ok={ok}, entry={e}")


def test_update_history_no_match_returns_false():
    """h2: 該当 entry が無ければ False return、history 不変。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "h.json"
        _seed_history(path, [
            {
                "displayed_on": "2026-05-04",
                "article_url": "https://x.test/different",
                "ai_kamiyama_called": False,
                "ai_kamiyama_failed": False,
                "fallback_used": False,
            },
        ])
        ok = serendipity_selector.update_history_column_fields(
            target_date=date(2026, 5, 4),
            article_url="https://x.test/no-such-url",
            ai_kamiyama_called=True,
            ai_kamiyama_failed=False,
            fallback_used=False,
            history_path=path,
        )
        loaded = serendipity_selector.load_history(path=path)
    e = loaded["history"][0]
    _check("h2 no match: returns False, history untouched",
           ok is False
           and e["ai_kamiyama_called"] is False
           and e["ai_kamiyama_failed"] is False
           and e["fallback_used"] is False,
           f"ok={ok}, entry={e}")


def test_update_history_multiple_match_updates_latest():
    """h3: 同じ (date, url) が複数 entries にあれば最新（末尾）を更新。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "h.json"
        _seed_history(path, [
            {
                "displayed_on": "2026-05-04",
                "article_url": "https://x.test/dup",
                "_tag": "old",
                "ai_kamiyama_called": False,
                "ai_kamiyama_failed": False,
                "fallback_used": False,
            },
            {
                "displayed_on": "2026-05-04",
                "article_url": "https://x.test/dup",
                "_tag": "new",
                "ai_kamiyama_called": False,
                "ai_kamiyama_failed": False,
                "fallback_used": False,
            },
        ])
        ok = serendipity_selector.update_history_column_fields(
            target_date=date(2026, 5, 4),
            article_url="https://x.test/dup",
            ai_kamiyama_called=True,
            ai_kamiyama_failed=False,
            fallback_used=False,
            history_path=path,
        )
        loaded = serendipity_selector.load_history(path=path)
    old, new = loaded["history"]
    _check("h3 duplicate match: only the latest (last) entry is updated",
           ok is True
           and old["_tag"] == "old"
           and old["ai_kamiyama_called"] is False  # untouched
           and new["_tag"] == "new"
           and new["ai_kamiyama_called"] is True,  # updated
           f"old.called={old['ai_kamiyama_called']}, "
           f"new.called={new['ai_kamiyama_called']}")


def test_update_history_normal_success_pattern():
    """h4: ai_kamiyama_called=True, failed=False, fallback=False の正常パターン。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "h.json"
        _seed_history(path, [{
            "displayed_on": "2026-05-04",
            "article_url": "https://x.test/ok",
            "ai_kamiyama_called": False,
            "ai_kamiyama_failed": False,
            "fallback_used": False,
        }])
        serendipity_selector.update_history_column_fields(
            target_date=date(2026, 5, 4),
            article_url="https://x.test/ok",
            ai_kamiyama_called=True,
            ai_kamiyama_failed=False,
            fallback_used=False,
            history_path=path,
        )
        e = serendipity_selector.load_history(path=path)["history"][0]
    _check("h4 normal column success → called=T, failed=F, fallback=F",
           e["ai_kamiyama_called"] is True
           and e["ai_kamiyama_failed"] is False
           and e["fallback_used"] is False)


def test_update_history_api_failure_pattern():
    """h5: ai_kamiyama_called=True, failed=True, fallback=True の API 失敗パターン。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "h.json"
        _seed_history(path, [{
            "displayed_on": "2026-05-04",
            "article_url": "https://x.test/fail",
            "ai_kamiyama_called": False,
            "ai_kamiyama_failed": False,
            "fallback_used": False,
        }])
        serendipity_selector.update_history_column_fields(
            target_date=date(2026, 5, 4),
            article_url="https://x.test/fail",
            ai_kamiyama_called=True,
            ai_kamiyama_failed=True,
            fallback_used=True,
            history_path=path,
        )
        e = serendipity_selector.load_history(path=path)["history"][0]
    _check("h5 API failure → called=T, failed=T, fallback=T",
           e["ai_kamiyama_called"] is True
           and e["ai_kamiyama_failed"] is True
           and e["fallback_used"] is True)


def test_update_history_atomic_json_intact():
    """h6: history 書込後、JSON 構造が破壊されず他 entries も intact。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "h.json"
        # 3 entries: one to update (middle), two siblings
        _seed_history(path, [
            {
                "displayed_on": "2026-05-03",
                "article_url": "https://x.test/sibling-old",
                "_marker": "sibling_a",
                "ai_kamiyama_called": False,
                "ai_kamiyama_failed": False,
                "fallback_used": False,
            },
            {
                "displayed_on": "2026-05-04",
                "article_url": "https://x.test/target",
                "_marker": "target",
                "ai_kamiyama_called": False,
                "ai_kamiyama_failed": False,
                "fallback_used": False,
            },
            {
                "displayed_on": "2026-05-05",
                "article_url": "https://x.test/sibling-new",
                "_marker": "sibling_b",
                "ai_kamiyama_called": False,
                "ai_kamiyama_failed": False,
                "fallback_used": False,
            },
        ])
        serendipity_selector.update_history_column_fields(
            target_date=date(2026, 5, 4),
            article_url="https://x.test/target",
            ai_kamiyama_called=True,
            ai_kamiyama_failed=False,
            fallback_used=False,
            history_path=path,
        )
        # File still parseable (load_history doesn't throw)
        loaded = serendipity_selector.load_history(path=path)
    a, t, b = loaded["history"]
    ok = (
        len(loaded["history"]) == 3
        and a["_marker"] == "sibling_a" and a["ai_kamiyama_called"] is False
        and t["_marker"] == "target" and t["ai_kamiyama_called"] is True
        and b["_marker"] == "sibling_b" and b["ai_kamiyama_called"] is False
    )
    _check("h6 JSON intact, only target updated, siblings untouched", ok,
           f"a={a['ai_kamiyama_called']}, t={t['ai_kamiyama_called']}, b={b['ai_kamiyama_called']}")


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
    print("(f) Culture category integration:")
    test_culture_in_eligible_categories()
    test_culture_pickable_when_least_shown()
    test_culture_participates_in_tie_random()
    print()
    print("(g) B1 改修：Reference priority も fetch:")
    test_fetch_calls_include_reference_priority()
    test_reference_articles_reach_pipeline_input()
    print()
    print("(h) Sprint 5 task #5: update_history_column_fields:")
    test_update_history_match_found_returns_true_and_updates()
    test_update_history_no_match_returns_false()
    test_update_history_multiple_match_updates_latest()
    test_update_history_normal_success_pattern()
    test_update_history_api_failure_pattern()
    test_update_history_atomic_json_intact()
    print()
    print(f"=== {PASS} passed, {FAIL} failed ===")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
