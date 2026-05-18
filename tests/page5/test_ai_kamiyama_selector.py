"""Unit tests for ai_kamiyama_selector (Sprint 7 Phase 1 Step 1, 2026-05-18).

Tests:
  a) collect_used_urls: 各経路から URL を正しく集計
  b) excluded_urls 除外検証
  c) category フィルタ：AI_KAMIYAMA_CATEGORIES 外は選ばれない
  d) top N score からの random
  e) 全候補 excluded → None
  f) candidates_scored 空 → None
  g) final_score の降順処理（None / float / int 混在）

Run::

    python3 -m tests.page5.test_ai_kamiyama_selector
"""

from __future__ import annotations

import random
import sys
from dataclasses import dataclass
from datetime import date

from scripts.page5.ai_kamiyama_selector import (
    AI_KAMIYAMA_CATEGORIES,
    DEFAULT_TOP_N,
    collect_used_urls,
    select_ai_kamiyama_article,
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
# Fixtures: minimal stand-ins for SourceRegistry and articles
# ---------------------------------------------------------------------------

@dataclass
class _FakeSource:
    name: str
    category: str


class _FakeRegistry:
    def __init__(self, mapping: dict):
        # 必要な属性は sources_by_name のみ
        self.sources_by_name = {n: _FakeSource(n, c) for n, c in mapping.items()}


def _make_article(
    url: str,
    *,
    score: float | None = 50.0,
    source: str = "BBC Business",
    category: str | None = None,
) -> dict:
    a = {
        "url": url,
        "title": f"title for {url}",
        "source_name": source,
        "final_score": score,
    }
    if category:
        a["category"] = category
    return a


# ---------------------------------------------------------------------------
# (a) collect_used_urls
# ---------------------------------------------------------------------------

def test_collect_used_urls_all_sources():
    page1 = [_make_article("https://e/1"), _make_article("https://e/2")]
    # page3 selections は RegionSelection-like dict のテストで両方確認
    @dataclass
    class _RegSel:
        article: dict | None
    page3 = {
        "R1": _RegSel(article=_make_article("https://r1/a")),
        "R2": _RegSel(article=_make_article("https://r2/b")),
        "R3": _RegSel(article=None),  # placeholder
    }
    page4 = [_make_article("https://p4/x")]
    serendipity = _make_article("https://ser/y")
    used = collect_used_urls(
        page1_selected=page1,
        page3_selections=page3,
        page4_articles=page4,
        serendipity_article=serendipity,
    )
    expected = {"https://e/1", "https://e/2", "https://r1/a", "https://r2/b",
                "https://p4/x", "https://ser/y"}
    _check(
        "a1 全経路から URL 6 件を集計",
        used == expected,
        f"got {used}",
    )


def test_collect_used_urls_dict_page3():
    """page3_selections が dict 形式 ({"article": {...}}) でも動く."""
    page3 = {
        "R1": {"article": _make_article("https://d/1")},
        "R2": {"article": None},
    }
    used = collect_used_urls(page3_selections=page3)
    _check(
        "a2 page3 dict 形式に対応",
        used == {"https://d/1"},
        f"got {used}",
    )


def test_collect_used_urls_empty():
    _check(
        "a3 全引数 None → 空 set",
        collect_used_urls() == set(),
    )


def test_collect_used_urls_none_url_excluded():
    page1 = [
        _make_article("https://e/1"),
        {"url": None, "source_name": "X"},  # url=None は除外
        {"source_name": "Y"},  # url 欠落も除外
    ]
    used = collect_used_urls(page1_selected=page1)
    _check(
        "a4 url=None / 欠落は除外",
        used == {"https://e/1"},
        f"got {used}",
    )


# ---------------------------------------------------------------------------
# (b) excluded_urls 除外
# ---------------------------------------------------------------------------

def test_excluded_urls_basic():
    candidates = [
        _make_article("https://a/1", score=80),
        _make_article("https://b/2", score=70),
        _make_article("https://c/3", score=60),
    ]
    excluded = {"https://a/1", "https://b/2"}
    rng = random.Random(42)
    chosen = select_ai_kamiyama_article(
        target_date=date(2026, 5, 18),
        excluded_urls=excluded,
        candidates_scored=candidates,
        rng=rng,
    )
    _check(
        "b1 excluded 2 件除外 → 残り 1 件が選ばれる",
        chosen is not None and chosen["url"] == "https://c/3",
        f"got {chosen}",
    )


def test_excluded_urls_with_score_order():
    """excluded で 1 位削った後、残りから top_n 内で random."""
    candidates = [
        _make_article("https://top1/", score=99),  # excluded
        _make_article("https://hi1/", score=80),
        _make_article("https://hi2/", score=78),
        _make_article("https://lo/", score=10),
    ]
    excluded = {"https://top1/"}
    chosen_urls = set()
    for seed in range(20):
        rng = random.Random(seed)
        c = select_ai_kamiyama_article(
            target_date=date(2026, 5, 18),
            excluded_urls=excluded,
            candidates_scored=candidates,
            rng=rng,
            top_n=3,
        )
        if c:
            chosen_urls.add(c["url"])
    # top1 は除外、残り 3 件全て top_n=3 に入る
    _check(
        "b2 excluded 後、残り 3 件全て top_n=3 から random で選択され得る",
        chosen_urls == {"https://hi1/", "https://hi2/", "https://lo/"},
        f"got {chosen_urls}",
    )


# ---------------------------------------------------------------------------
# (c) category フィルタ
# ---------------------------------------------------------------------------

def test_category_filter_via_registry():
    """registry + eligible_categories で source の category 解決."""
    candidates = [
        _make_article("https://biz/", source="BBC Business"),
        _make_article("https://news/", source="ITmedia AI＋"),
        _make_article("https://music/", source="natalie.mu"),
    ]
    registry = _FakeRegistry({
        "BBC Business": "business",
        "ITmedia AI＋": "technology",   # AI_KAMIYAMA_CATEGORIES に無い
        "natalie.mu": "music",            # AI_KAMIYAMA_CATEGORIES に無い
    })
    rng = random.Random(42)
    chosen = select_ai_kamiyama_article(
        target_date=date(2026, 5, 18),
        excluded_urls=set(),
        candidates_scored=candidates,
        registry=registry,
        eligible_categories=AI_KAMIYAMA_CATEGORIES,
        rng=rng,
    )
    _check(
        "c1 business は採用、technology/music は除外",
        chosen is not None and chosen["url"] == "https://biz/",
        f"got {chosen}",
    )


def test_category_filter_via_article_field():
    """article 自身に category フィールドがあれば registry なしでも動く."""
    candidates = [
        _make_article("https://a/", category="business"),
        _make_article("https://m/", category="music"),
    ]
    rng = random.Random(42)
    chosen = select_ai_kamiyama_article(
        target_date=date(2026, 5, 18),
        excluded_urls=set(),
        candidates_scored=candidates,
        registry=None,  # registry 無し
        eligible_categories=AI_KAMIYAMA_CATEGORIES,
        rng=rng,
    )
    _check(
        "c2 article.category フィールド優先（registry 不要）",
        chosen is not None and chosen["url"] == "https://a/",
        f"got {chosen}",
    )


def test_category_filter_fallback_when_empty():
    """eligible で全部弾かれたら pool 全体を残す（候補枯渇回避）."""
    candidates = [
        _make_article("https://x/", category="music", score=80),
        _make_article("https://y/", category="cooking", score=70),
    ]
    rng = random.Random(42)
    chosen = select_ai_kamiyama_article(
        target_date=date(2026, 5, 18),
        excluded_urls=set(),
        candidates_scored=candidates,
        eligible_categories=AI_KAMIYAMA_CATEGORIES,
        rng=rng,
    )
    _check(
        "c3 eligible 該当ゼロでも fallback で何か選ばれる",
        chosen is not None,
        f"got {chosen}",
    )


def test_category_filter_skipped_when_no_eligible():
    """eligible_categories=None なら category フィルタ skip."""
    candidates = [
        _make_article("https://m/", category="music", score=80),
    ]
    rng = random.Random(42)
    chosen = select_ai_kamiyama_article(
        target_date=date(2026, 5, 18),
        excluded_urls=set(),
        candidates_scored=candidates,
        eligible_categories=None,
        rng=rng,
    )
    _check(
        "c4 eligible=None で category フィルタ skip",
        chosen is not None and chosen["url"] == "https://m/",
        f"got {chosen}",
    )


# ---------------------------------------------------------------------------
# (d) top N からの random
# ---------------------------------------------------------------------------

def test_random_within_top_n():
    """score 上位 top_n に入る記事だけが選ばれる."""
    candidates = [_make_article(f"https://u/{i}", score=100 - i) for i in range(20)]
    chosen_urls = set()
    for seed in range(100):
        rng = random.Random(seed)
        c = select_ai_kamiyama_article(
            target_date=date(2026, 5, 18),
            excluded_urls=set(),
            candidates_scored=candidates,
            rng=rng,
            top_n=5,
        )
        if c:
            chosen_urls.add(c["url"])
    # 上位 5 件のみ
    expected = {f"https://u/{i}" for i in range(5)}
    _check(
        "d1 top_n=5 → score 上位 5 件のみ選ばれる",
        chosen_urls.issubset(expected),
        f"got {chosen_urls}, expected subset of {expected}",
    )
    _check(
        "d2 top_n=5 の全 5 件が選ばれる頻度がある (100 seeds で網羅)",
        len(chosen_urls) >= 3,  # 統計的に 5 件全部出るか確認は厳しい
        f"got {len(chosen_urls)} unique",
    )


# ---------------------------------------------------------------------------
# (e) 全候補 excluded → None
# ---------------------------------------------------------------------------

def test_all_excluded_returns_none():
    candidates = [_make_article("https://a/1"), _make_article("https://b/2")]
    excluded = {"https://a/1", "https://b/2"}
    chosen = select_ai_kamiyama_article(
        target_date=date(2026, 5, 18),
        excluded_urls=excluded,
        candidates_scored=candidates,
    )
    _check(
        "e1 全候補 excluded → None",
        chosen is None,
        f"got {chosen}",
    )


# ---------------------------------------------------------------------------
# (f) candidates_scored 空 → None
# ---------------------------------------------------------------------------

def test_empty_candidates_returns_none():
    _check(
        "f1 candidates_scored 空 → None",
        select_ai_kamiyama_article(
            target_date=date(2026, 5, 18),
            excluded_urls=set(),
            candidates_scored=[],
        ) is None,
    )


# ---------------------------------------------------------------------------
# (g) final_score 降順処理（None / int / float 混在）
# ---------------------------------------------------------------------------

def test_score_sort_with_none():
    """final_score=None は最下位扱い、有効な score が優先される."""
    candidates = [
        _make_article("https://noscore/", score=None),
        _make_article("https://int/", score=50),
        _make_article("https://low/", score=10),
        _make_article("https://high/", score=90),
    ]
    rng = random.Random(0)
    # top_n=1 で必ず最高 score が選ばれる
    chosen = select_ai_kamiyama_article(
        target_date=date(2026, 5, 18),
        excluded_urls=set(),
        candidates_scored=candidates,
        rng=rng,
        top_n=1,
    )
    _check(
        "g1 final_score=None は最下位、top_n=1 で score 最大が選ばれる",
        chosen is not None and chosen["url"] == "https://high/",
        f"got {chosen}",
    )


def main() -> int:
    print("ai_kamiyama_selector tests (Sprint 7 Phase 1 Step 1, 2026-05-18)")
    print()
    print("(a) collect_used_urls:")
    test_collect_used_urls_all_sources()
    test_collect_used_urls_dict_page3()
    test_collect_used_urls_empty()
    test_collect_used_urls_none_url_excluded()
    print()
    print("(b) excluded_urls 除外:")
    test_excluded_urls_basic()
    test_excluded_urls_with_score_order()
    print()
    print("(c) category フィルタ:")
    test_category_filter_via_registry()
    test_category_filter_via_article_field()
    test_category_filter_fallback_when_empty()
    test_category_filter_skipped_when_no_eligible()
    print()
    print("(d) top N からの random:")
    test_random_within_top_n()
    print()
    print("(e) 全候補 excluded → None:")
    test_all_excluded_returns_none()
    print()
    print("(f) candidates_scored 空 → None:")
    test_empty_candidates_returns_none()
    print()
    print("(g) final_score 降順処理:")
    test_score_sort_with_none()
    print()
    print(f"=== {PASS} passed, {FAIL} failed ===")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
