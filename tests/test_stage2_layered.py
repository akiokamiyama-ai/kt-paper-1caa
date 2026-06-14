"""Unit tests for stage2.py layered mode (C85 Sub-Step 2-4).

Phase B Step 4: 3 層構造 Stage 2 の本実装を検証する。LLM 呼び出しは行わず、
classify / threshold filter / dataclass / feature flag の dispatch を中心に。

Run::

    python3 -m tests.test_stage2_layered
"""

from __future__ import annotations

import sys

from scripts.selector import stage2
from scripts.selector.stage2 import (
    LayerConfig,
    Stage2Result,
    _classify_articles,
    _filter_top,
    KNOWN_CALLERS,
    DEFAULT_HAIKU_MODEL,
    DEFAULT_MODEL,
    run_stage2,
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
# (a) LayerConfig dataclass
# ---------------------------------------------------------------------------

def test_default_layer_config_is_disabled():
    cfg = LayerConfig()
    _check("a1 LayerConfig() のデフォルト: enabled=False (legacy 動作維持)",
           cfg.enabled is False)
    _check("a2 デフォルト n_master=0.30", cfg.n_master == 0.30)
    _check("a3 デフォルト n_page3=0.20", cfg.n_page3 == 0.20)
    _check("a4 デフォルト k_threshold=15", cfg.k_threshold == 15)
    _check("a5 デフォルト haiku_model = claude-haiku-4-5",
           cfg.haiku_model == "claude-haiku-4-5")
    _check("a6 デフォルト sonnet_model = claude-sonnet-4-6",
           cfg.sonnet_model == "claude-sonnet-4-6")


def test_n_for_caller_defaults():
    cfg = LayerConfig()
    _check("a7 n_for_caller('page1_master') = n_master = 0.30",
           cfg.n_for_caller("page1_master") == 0.30)
    _check("a8 n_for_caller('page3') = n_page3 = 0.20",
           cfg.n_for_caller("page3") == 0.20)
    _check("a9 n_for_caller('page4') (未指定) = n_master fallback",
           cfg.n_for_caller("page4") == 0.30)


def test_n_for_caller_with_overrides():
    cfg = LayerConfig(
        caller_n_overrides=(("page2", 0.25), ("page4", 0.40)),
    )
    _check("a10 caller_n_overrides 'page2' = 0.25", cfg.n_for_caller("page2") == 0.25)
    _check("a11 caller_n_overrides 'page4' = 0.40", cfg.n_for_caller("page4") == 0.40)
    _check("a12 caller_n_overrides 未指定 'page3' は n_page3 維持",
           cfg.n_for_caller("page3") == 0.20)


def test_known_callers_set():
    expected = {"page1_master", "page3", "page2", "page4", "page5", "page6"}
    _check("a13 KNOWN_CALLERS が 6 件揃う",
           set(KNOWN_CALLERS) == expected,
           f"got {set(KNOWN_CALLERS)}")


# ---------------------------------------------------------------------------
# (b) run_stage2 dispatch (feature flag)
# ---------------------------------------------------------------------------

def test_run_stage2_empty_articles_legacy():
    r = run_stage2([])
    _check("b1 empty articles + no layer_config → legacy 経路、空 result",
           isinstance(r, Stage2Result) and r.batches_run == 0
           and r.model == DEFAULT_MODEL)


def test_run_stage2_empty_articles_disabled_config():
    """layer_config=LayerConfig(enabled=False) は legacy 経路を使う."""
    r = run_stage2([], layer_config=LayerConfig())
    _check("b2 LayerConfig(enabled=False) → legacy 経路",
           r.batches_run == 0 and r.model == DEFAULT_MODEL)


def test_run_stage2_empty_articles_layered():
    """layer_config=LayerConfig(enabled=True) で空 article は空 result を返す."""
    r = run_stage2([], layer_config=LayerConfig(enabled=True), caller="page1_master")
    _check("b3 layered モード empty articles → 空 result (model に 'layered' 含む)",
           r.batches_run == 0 and "layered" in r.model,
           f"got model={r.model!r}")


# ---------------------------------------------------------------------------
# (c) _classify_articles
# ---------------------------------------------------------------------------

def test_classify_articles_basic():
    arts = [
        {"source_name": "BBC Business",         "category": "business"},
        {"source_name": "Foresight（新潮社）",     "category": "geopolitics"},
        {"source_name": "東洋経済オンライン",         "category": "business"},
    ]
    l1, l2, l3 = _classify_articles(arts)
    _check("c1 BBC → layer 1, 東洋経済 → layer 2, Foresight → layer 3",
           len(l1) == 1 and len(l2) == 1 and len(l3) == 1
           and l1[0]["source_name"] == "BBC Business"
           and l2[0]["source_name"] == "東洋経済オンライン"
           and l3[0]["source_name"] == "Foresight（新潮社）",
           f"l1={[a['source_name'] for a in l1]} l2={[a['source_name'] for a in l2]} l3={[a['source_name'] for a in l3]}")


def test_classify_articles_que_dynamic():
    arts = [
        {"source_name": "Shincho QUE（新潮QUE）", "category": "business"},
        {"source_name": "Shincho QUE（新潮QUE）", "category": "geopolitics"},
    ]
    l1, l2, l3 = _classify_articles(arts)
    _check("c2 QUE business → layer 1, QUE geopolitics → layer 3",
           len(l1) == 1 and len(l3) == 1 and len(l2) == 0)


def test_classify_articles_c84_promoted():
    arts = [
        {"source_name": "McKinsey Insights", "category": "business"},
        {"source_name": "Nautilus", "category": "books:自然科学ノンフィクション"},
    ]
    l1, l2, l3 = _classify_articles(arts)
    _check("c3 C84 昇格 (McKinsey + Nautilus) → 両方 layer 3",
           len(l3) == 2 and len(l2) == 0 and len(l1) == 0)


def test_classify_articles_empty():
    l1, l2, l3 = _classify_articles([])
    _check("c4 empty → ([], [], [])", l1 == [] and l2 == [] and l3 == [])


# ---------------------------------------------------------------------------
# (d) _filter_top (ハイブリッド閾値 = top N% AND score>=K)
# ---------------------------------------------------------------------------

def _ev(a1: int, a3: int, a8: int) -> dict:
    return {
        "scores": {
            "aesthetic_1_structure_detail":    a1,
            "aesthetic_3_disciplinary_bridge": a3,
            "aesthetic_8_behavioral_economics": a8,
        }
    }


def test_filter_top_ratio_30_pct():
    evals = [
        ({"url": f"u{i}"}, _ev(s // 3 + 1, s // 3 + 1, s // 3 + 1))
        for i, s in enumerate([30, 24, 21, 18, 15, 9, 6, 3])  # 8 entries
    ]
    top, rest = _filter_top(evals, ratio=0.30, min_score=15)
    # 8 × 0.30 = 2.4 → top=2、ただし上位 score ≥ 15 を満たす全件
    top_urls = sorted(a["url"] for a, _ in top)
    _check("d1 ratio=30% / K=15 / 8 entries → 上位 2 件 (両方 score>=15)",
           len(top) == 2 and top_urls == ["u0", "u1"],
           f"got top urls = {top_urls}")


def test_filter_top_k_floor_kicks_in():
    """全 entry が K=15 未満なら top は空."""
    evals = [
        ({"url": f"u{i}"}, _ev(2, 2, 2))  # sum=6
        for i in range(5)
    ]
    top, rest = _filter_top(evals, ratio=0.50, min_score=15)
    _check("d2 全 entry score<15 → top=[] (K でカット)",
           top == [] and len(rest) == 5)


def test_filter_top_empty():
    top, rest = _filter_top([], ratio=0.30, min_score=15)
    _check("d3 empty → ([], [])", top == [] and rest == [])


def test_filter_top_at_least_one_top():
    """ratio が極端に小さくても最低 1 件は top に入る（max(1, int(N*ratio))）.

    これにより全 source が空ということがない（少なくとも先頭 1 件は Sonnet 化）。
    """
    evals = [({"url": f"u{i}"}, _ev(8, 9, 7)) for i in range(10)]  # sum=24
    top, rest = _filter_top(evals, ratio=0.05, min_score=15)
    _check("d4 ratio=5% でも 1 件以上 top に入る",
           len(top) >= 1)


def test_filter_top_sort_by_score_desc():
    """top は score 降順に並ぶ。"""
    evals = [
        ({"url": "lo"},  _ev(3, 4, 3)),    # sum=10
        ({"url": "hi"},  _ev(9, 9, 8)),    # sum=26
        ({"url": "mid"}, _ev(6, 6, 5)),    # sum=17
    ]
    top, _ = _filter_top(evals, ratio=1.0, min_score=15)
    top_urls = [a["url"] for a, _ in top]
    _check("d5 _filter_top は score 降順 (hi → mid)",
           top_urls == ["hi", "mid"],
           f"got {top_urls}")


# ---------------------------------------------------------------------------
# (e) Stage2Result merge sanity（layered モードが Stage2Result を正しく集約）
# ---------------------------------------------------------------------------

def test_stage2_result_default_state():
    r = Stage2Result()
    _check("e1 Stage2Result デフォルト: batches=0, cost=0, errors=[]",
           r.batches_run == 0 and r.cost_usd == 0.0 and r.errors == []
           and r.evaluations_by_url == {})


def main() -> int:
    print("stage2 layered mode unit tests (C85 Sub-Step 2-4)")
    print()
    print("(a) LayerConfig:")
    test_default_layer_config_is_disabled()
    test_n_for_caller_defaults()
    test_n_for_caller_with_overrides()
    test_known_callers_set()

    print()
    print("(b) run_stage2 dispatch (feature flag):")
    test_run_stage2_empty_articles_legacy()
    test_run_stage2_empty_articles_disabled_config()
    test_run_stage2_empty_articles_layered()

    print()
    print("(c) _classify_articles:")
    test_classify_articles_basic()
    test_classify_articles_que_dynamic()
    test_classify_articles_c84_promoted()
    test_classify_articles_empty()

    print()
    print("(d) _filter_top (ハイブリッド閾値):")
    test_filter_top_ratio_30_pct()
    test_filter_top_k_floor_kicks_in()
    test_filter_top_empty()
    test_filter_top_at_least_one_top()
    test_filter_top_sort_by_score_desc()

    print()
    print("(e) Stage2Result:")
    test_stage2_result_default_state()

    print()
    print(f"=== {PASS} passed, {FAIL} failed ===")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
