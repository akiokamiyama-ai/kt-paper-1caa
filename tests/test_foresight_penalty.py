"""Unit tests for Page I source-based soft penalty (Sprint 6, 2026-05-03).

Tests:
  a) _apply_page1_source_penalty: Foresight returns -5, others 0
  b) _apply_page1_source_penalty: variant source_name patterns
  c) run_pipeline: applies penalty to Foresight article and re-sorts
  d) run_pipeline: non-Foresight scored articles unchanged
  e) penalty NEVER bleeds into other pages (verify _apply_page1_source_penalty
     is only called from run_pipeline, not from page2/4/5/6 selectors)

Run::

    python3 -m tests.test_foresight_penalty
"""

from __future__ import annotations

import io
import sys

from scripts import regen_front_page_v2 as regen

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
# (a) _apply_page1_source_penalty: Foresight detection
# ---------------------------------------------------------------------------

def test_penalty_foresight_detected():
    article = {"source_name": "Foresight（新潮社）", "title": "x"}
    p = regen._apply_page1_source_penalty(article)
    _check("a1 'Foresight（新潮社）' → -10.0", p == -10.0, f"got {p}")


def test_penalty_foresight_short_form():
    """Substring match should work for 'Foresight' in any wrapping."""
    article = {"source_name": "Foresight", "title": "x"}
    p = regen._apply_page1_source_penalty(article)
    _check("a2 plain 'Foresight' → -10.0", p == -10.0, f"got {p}")


def test_penalty_other_sources_zero():
    for source in (
        "The Economist",
        "BBC Business",
        "Reuters Business",
        "日本経済新聞",
        "東洋経済オンライン",
        "Harvard Business Review（HBR.org）",
        "Forbes Japan",
        "ITmedia AI＋",
    ):
        article = {"source_name": source, "title": "x"}
        p = regen._apply_page1_source_penalty(article)
        _check(f"a3 '{source}' → 0.0", p == 0.0, f"got {p}")


def test_penalty_empty_source_zero():
    _check("a4 missing source_name → 0.0",
           regen._apply_page1_source_penalty({"title": "x"}) == 0.0)
    _check("a5 None source_name → 0.0",
           regen._apply_page1_source_penalty({"source_name": None, "title": "x"}) == 0.0)


# ---------------------------------------------------------------------------
# (b) Constants are at expected magnitude (sanity)
# ---------------------------------------------------------------------------

def test_penalty_constant_magnitude():
    _check("b1 FORESIGHT_PENALTY == -10.0", regen.FORESIGHT_PENALTY == -10.0)
    _check("b2 'Foresight' in FORESIGHT_PATTERNS",
           "Foresight" in regen.FORESIGHT_PATTERNS)


# ---------------------------------------------------------------------------
# (c) run_pipeline applies penalty + re-sorts
# ---------------------------------------------------------------------------

def test_run_pipeline_demotes_foresight():
    """Foresight at score 38 + Economist at 36: penalty pushes Foresight below.

    Sprint 5 ポストモーメント (2026-05-04): penalty -10 強化後、Foresight 38 →
    28 に降格、Economist 36 が TOP に。
    """
    # Mock the pipeline internals so we don't run actual LLM/network.
    from scripts.lib.source import Article
    from datetime import datetime

    fake_articles = [
        Article(source_name="Foresight（新潮社）", title="JP article",
                link="https://fsight/1", description="d",
                pub_date=datetime(2026, 5, 3)),
        Article(source_name="The Economist", title="EN article",
                link="https://e/1", description="d",
                pub_date=datetime(2026, 5, 3)),
    ]

    # mock run_stage1 → all surviving
    original_s1 = regen.run_stage1
    regen.run_stage1 = lambda dicts: [{**d, "is_excluded": False} for d in dicts]

    # mock run_stage2 → Foresight scores higher pre-penalty
    class FakeS2:
        evaluations_by_url = {
            "https://fsight/1": {"final_score": 38.0, "美意識1": 8},
            "https://e/1": {"final_score": 36.0, "美意識1": 7},
        }
        cost_usd = 0.0
        errors = []
    original_s2 = regen.run_stage2
    regen.run_stage2 = lambda arts: FakeS2()

    # mock integrate_scores → no-op (final_score already in evaluations_by_url)
    original_int = regen.integrate_scores
    regen.integrate_scores = lambda d: None

    captured = io.StringIO()
    original_stderr = sys.stderr
    sys.stderr = captured
    try:
        result = regen.run_pipeline(fake_articles)
    finally:
        sys.stderr = original_stderr
        regen.run_stage1 = original_s1
        regen.run_stage2 = original_s2
        regen.integrate_scores = original_int

    log = captured.getvalue()
    # Top after sort should be Economist (36.0) since Foresight was demoted to 28.0
    top = result.candidates_scored[0]
    foresight_demoted = any(
        a.get("source_name") == "Foresight（新潮社）"
        and a.get("final_score") == 28.0
        and a.get("page1_source_penalty") == -10.0
        for a in result.candidates_scored
    )
    _check("c1 Economist (36.0) outranks demoted Foresight (38→28)",
           top.get("source_name") == "The Economist",
           f"top={top.get('source_name')}/{top.get('final_score')}")
    _check("c2 Foresight final_score updated 38→28, penalty recorded (-10)",
           foresight_demoted,
           f"foresight={[a for a in result.candidates_scored if 'Foresight' in (a.get('source_name') or '')]}")
    _check("c3 stderr log mentions 'source penalty'", "source penalty" in log,
           f"log:\n{log}")


def test_run_pipeline_economist_unchanged():
    """The Economist article keeps its final_score; no penalty applied."""
    from scripts.lib.source import Article
    from datetime import datetime

    fake_articles = [
        Article(source_name="The Economist", title="EN article",
                link="https://e/1", description="d",
                pub_date=datetime(2026, 5, 3)),
    ]
    original_s1 = regen.run_stage1
    regen.run_stage1 = lambda dicts: [{**d, "is_excluded": False} for d in dicts]
    class FakeS2:
        evaluations_by_url = {
            "https://e/1": {"final_score": 30.0, "美意識1": 7},
        }
        cost_usd = 0.0
        errors = []
    original_s2 = regen.run_stage2
    regen.run_stage2 = lambda arts: FakeS2()
    original_int = regen.integrate_scores
    regen.integrate_scores = lambda d: None
    try:
        result = regen.run_pipeline(fake_articles)
    finally:
        regen.run_stage1 = original_s1
        regen.run_stage2 = original_s2
        regen.integrate_scores = original_int
    economist = result.candidates_scored[0]
    _check("c4 Economist final_score unchanged at 30.0",
           economist.get("final_score") == 30.0,
           f"got {economist.get('final_score')}")
    _check("c5 Economist has no page1_source_penalty key",
           "page1_source_penalty" not in economist)


# ---------------------------------------------------------------------------
# (d) Penalty isolated to Page I — verify other selectors don't import it
# ---------------------------------------------------------------------------

def test_penalty_not_used_by_other_selectors():
    """Page IV/V/VI selectors must not call _apply_page1_source_penalty."""
    import scripts.page4.article_rotator as p4
    import scripts.page5.serendipity_selector as p5
    import scripts.page6.leisure_recommender as p6
    import scripts.selector.page2 as page2
    import scripts.selector.page3 as page3
    for mod_name, mod in [
        ("page4.article_rotator", p4),
        ("page5.serendipity_selector", p5),
        ("page6.leisure_recommender", p6),
        ("selector.page2", page2),
        ("selector.page3", page3),
    ]:
        # If the module had imported _apply_page1_source_penalty, it would be
        # in module dict.
        has_it = hasattr(mod, "_apply_page1_source_penalty")
        _check(
            f"d {mod_name}: does NOT have _apply_page1_source_penalty",
            not has_it,
        )


def main() -> int:
    print("Foresight soft penalty tests (Sprint 6, 2026-05-03)")
    print()
    print("(a) _apply_page1_source_penalty Foresight detection:")
    test_penalty_foresight_detected()
    test_penalty_foresight_short_form()
    test_penalty_other_sources_zero()
    test_penalty_empty_source_zero()
    print()
    print("(b) Constants:")
    test_penalty_constant_magnitude()
    print()
    print("(c) run_pipeline applies penalty + re-sorts:")
    test_run_pipeline_demotes_foresight()
    test_run_pipeline_economist_unchanged()
    print()
    print("(d) Penalty isolated to Page I (not used by other selectors):")
    test_penalty_not_used_by_other_selectors()
    print()
    print(f"=== {PASS} passed, {FAIL} failed ===")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
