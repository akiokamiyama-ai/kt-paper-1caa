"""Unit tests for ai_kamiyama_selector (C40 第二弾, Sprint 8, 2026-05-30).

C40 第二弾の神山案で大幅再設計：
- 旧 ``candidates_scored`` 全体参照ロジック → 廃止
- 候補プール = 当日確定紙面（Page II Today's Headlines + Page III + Page IV
  学術記事） − Page V serendipity
- Page I は意図的に含めない（C45 D2 と同じ哲学）
- 過去日 dedup は他面の dedup（C40 案1+案2 で headlines 7日、page3 7日、
  page4 30日）が自動的にカバー

Tests:
  a) build_candidate_pool: 各経路から記事を集計、serendipity 除外、URL dedup
  b) Page I は候補プールに入らない（API 自体に page_one_selected 引数なし）
  c) serendipity URL が除外される
  d) URL 重複は順序保持で dedup
  e) select_ai_kamiyama_article: top_n / random / score 降順
  f) 候補ゼロ → None
  g) category フィルタ（任意、通常 skip）
  h) 連続日重複の自動回避（紙面 fixture を 2 日連続変えると別 URL が選ばれる）

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
    build_candidate_pool,
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
# Fixtures
# ---------------------------------------------------------------------------

@dataclass
class _FakeSource:
    name: str
    category: str


class _FakeRegistry:
    def __init__(self, mapping: dict):
        self.sources_by_name = {n: _FakeSource(n, c) for n, c in mapping.items()}


@dataclass
class _RegSel:
    """Page III の RegionSelection-like minimal fixture."""
    article: dict | None


def _make_article(
    url: str,
    *,
    score: float | None = 50.0,
    source: str = "BBC Business",
    category: str | None = None,
    title: str | None = None,
) -> dict:
    a = {
        "url": url,
        "title": title or f"title for {url}",
        "source_name": source,
        "final_score": score,
    }
    if category:
        a["category"] = category
    return a


# ---------------------------------------------------------------------------
# (a) build_candidate_pool: Page III 確定枠 + runner-up
#
# C155 (Sprint 13, 2026-08-10): 候補プールの構成を変更した。
# 旧: Today's Headlines + Page III + Page IV 学術記事 − serendipity
# 新: Page III 確定 6 枠（5 領域 + SER） + Page III runner-up
# ---------------------------------------------------------------------------

def test_pool_combines_page3_slots_and_runner_ups():
    page3 = {
        "R1": _RegSel(article=_make_article("https://r1/a")),
        "R4": _RegSel(article=_make_article("https://r4/b")),
        "R3": _RegSel(article=None),  # placeholder
        "SER": _RegSel(article=_make_article("https://ser/c")),
    }
    runner_ups = [
        _make_article("https://ru/x"),
        _make_article("https://ru/y"),
    ]
    pool = build_candidate_pool(
        page3_selections=page3, page3_runner_ups=runner_ups,
    )
    urls = {a["url"] for a in pool}
    _check(
        "a1 Page III 確定枠 + runner-up から計 5 件",
        urls == {"https://r1/a", "https://r4/b", "https://ser/c",
                 "https://ru/x", "https://ru/y"},
        f"got {urls}",
    )


def test_pool_includes_serendipity_slot():
    """C155: セレンディピティは Page III の 1 枠になったので候補に含む.

    旧構成では第5面上段の serendipity は「背中合わせ枠」として一筆の候補から
    除外していた。C155 で第3面に移り、他 5 記事と同格になったため除外理由が
    消えた。
    """
    page3 = {"SER": _RegSel(article=_make_article("https://ser/only"))}
    pool = build_candidate_pool(page3_selections=page3)
    _check(
        "a2 SER 枠の記事も候補に含まれる",
        [a["url"] for a in pool] == ["https://ser/only"],
        f"got {[a['url'] for a in pool]}",
    )


def test_pool_handles_page3_dict_shape():
    """page3_selections が dict 形式 ({"article": {...}}) でも動く."""
    page3 = {
        "R1": {"article": _make_article("https://d/1")},
        "R4": {"article": None},
    }
    pool = build_candidate_pool(page3_selections=page3)
    _check(
        "a3 page3 dict 形式に対応",
        [a["url"] for a in pool] == ["https://d/1"],
    )


def test_pool_empty_when_all_none():
    _check(
        "a4 全引数 None → 空 pool",
        build_candidate_pool() == [],
    )


def test_pool_skips_articles_without_url():
    runner_ups = [
        _make_article("https://ru/1"),
        {"title": "no url", "source_name": "X"},  # url 欠落
        {"url": None, "title": "null url"},
    ]
    pool = build_candidate_pool(page3_runner_ups=runner_ups)
    _check(
        "a5 url 欠落 / None は除外",
        [a["url"] for a in pool] == ["https://ru/1"],
    )


# ---------------------------------------------------------------------------
# (b) Page I は API に含まれない（構造的保証）
# ---------------------------------------------------------------------------

def test_no_page_one_parameter():
    """select_ai_kamiyama_article は Page I を一切受けない.

    C40 第二弾以降、Page I は候補プールに含まれない設計。C155 で Page I が
    週次 essay になった後もこの方針は維持する（editorial / 一筆と参照が
    重複するため）。
    """
    import inspect
    sig = inspect.signature(select_ai_kamiyama_article)
    params = set(sig.parameters.keys())
    _check(
        "b1 select API に page1_selected / candidates_scored / excluded_urls なし",
        "page1_selected" not in params
        and "candidates_scored" not in params
        and "excluded_urls" not in params,
        f"got params: {sorted(params)}",
    )
    _check(
        "b2 select API は page3_selections / page3_runner_ups を受ける",
        {"page3_selections", "page3_runner_ups"}.issubset(params),
        f"got params: {sorted(params)}",
    )
    _check(
        "b3 C155 で廃止した引数が残っていない",
        not {"page_two_headlines", "page4_articles",
             "serendipity_article"} & params,
        f"got params: {sorted(params)}",
    )


# ---------------------------------------------------------------------------
# (d) URL 重複は順序保持で dedup
# ---------------------------------------------------------------------------

def test_pool_dedups_same_url_across_sources():
    """同一 URL が確定枠と runner-up 両方に出た場合は先出（確定枠）が残る."""
    page3 = {"R1": _RegSel(article=_make_article("https://dup/"))}
    runner_ups = [_make_article("https://dup/"), _make_article("https://ru/2")]
    pool = build_candidate_pool(
        page3_selections=page3, page3_runner_ups=runner_ups,
    )
    urls = [a["url"] for a in pool]
    _check(
        "d1 同 URL が 2 経路で出ても 1 つだけ pool に残る（順序保持）",
        urls == ["https://dup/", "https://ru/2"],
        f"got {urls}",
    )


# ---------------------------------------------------------------------------
# (e) select_ai_kamiyama_article: top_n / score 降順 / random
# ---------------------------------------------------------------------------

def test_select_top_n_random_within_pool():
    """top_n=3 の場合、score 上位 3 件のみ候補。"""
    runner_ups = [_make_article(f"https://u/{i}", score=100 - i) for i in range(8)]
    chosen_urls = set()
    for seed in range(60):
        rng = random.Random(seed)
        chosen = select_ai_kamiyama_article(
            target_date=date(2026, 5, 31),
            page3_runner_ups=runner_ups,
            rng=rng,
            top_n=3,
        )
        if chosen:
            chosen_urls.add(chosen["url"])
    _check(
        "e1 top_n=3 → score 上位 3 件のみ選ばれる",
        chosen_urls.issubset({f"https://u/{i}" for i in range(3)}),
        f"got {chosen_urls}",
    )
    _check(
        "e2 60 seeds で複数 URL が出現（random 性を確認）",
        len(chosen_urls) >= 2,
        f"got {len(chosen_urls)} unique",
    )


def test_select_score_descending_top1():
    runner_ups = [
        _make_article("https://low/", score=10),
        _make_article("https://high/", score=99),
        _make_article("https://mid/", score=50),
    ]
    chosen = select_ai_kamiyama_article(
        target_date=date(2026, 5, 31),
        page3_runner_ups=runner_ups,
        rng=random.Random(0),
        top_n=1,
    )
    _check(
        "e3 top_n=1 で score 最大 (https://high/) が選ばれる",
        chosen is not None and chosen["url"] == "https://high/",
        f"got {chosen}",
    )


def test_select_score_none_treated_as_lowest():
    runner_ups = [
        _make_article("https://noscore/", score=None),
        _make_article("https://low/", score=10),
        _make_article("https://high/", score=90),
    ]
    chosen = select_ai_kamiyama_article(
        target_date=date(2026, 5, 31),
        page3_runner_ups=runner_ups,
        rng=random.Random(0),
        top_n=1,
    )
    _check(
        "e4 score=None は最下位、top_n=1 で score 最大が選ばれる",
        chosen is not None and chosen["url"] == "https://high/",
    )


# ---------------------------------------------------------------------------
# (f) 候補ゼロ → None
# ---------------------------------------------------------------------------

def test_select_empty_pool_returns_none():
    _check(
        "f1 全引数 None → None",
        select_ai_kamiyama_article(target_date=date(2026, 5, 31)) is None,
    )


def test_select_single_candidate_is_chosen():
    """C155: serendipity 除外ロジックは廃止。唯一候補はそのまま選ばれる.

    旧 f2 は「唯一の候補が serendipity と同 URL → None」を検証していたが、
    セレンディピティが Page III の 1 枠になり除外理由が消えたため差し替えた。
    """
    page3 = {"SER": _RegSel(article=_make_article("https://only/"))}
    chosen = select_ai_kamiyama_article(
        target_date=date(2026, 5, 31),
        page3_selections=page3,
        rng=random.Random(0),
    )
    _check(
        "f2 唯一候補（SER 枠）がそのまま選ばれる",
        chosen is not None and chosen["url"] == "https://only/",
        f"got {chosen}",
    )


# ---------------------------------------------------------------------------
# (g) category フィルタ（任意、通常 skip）
# ---------------------------------------------------------------------------

def test_select_no_category_filter_by_default():
    """eligible_categories=None なら category 関係なく全候補から選ばれる."""
    runner_ups = [
        _make_article("https://m/", category="music"),
    ]
    chosen = select_ai_kamiyama_article(
        target_date=date(2026, 5, 31),
        page3_runner_ups=runner_ups,
        eligible_categories=None,
        rng=random.Random(0),
    )
    _check(
        "g1 eligible=None → category 無視で music も選ばれる",
        chosen is not None and chosen["url"] == "https://m/",
    )


def test_select_with_explicit_category_filter():
    """eligible_categories を明示すれば フィルタが効く（後方互換）."""
    runner_ups = [
        _make_article("https://biz/", category="business"),
        _make_article("https://music/", category="music"),
    ]
    chosen = select_ai_kamiyama_article(
        target_date=date(2026, 5, 31),
        page3_runner_ups=runner_ups,
        eligible_categories=("business",),
        rng=random.Random(0),
        top_n=1,
    )
    _check(
        "g2 eligible=(business,) → music は除外、business のみ",
        chosen is not None and chosen["url"] == "https://biz/",
    )


def test_select_with_registry_lookup():
    """article.category なくても registry + source_name から解決."""
    runner_ups = [
        _make_article("https://biz/", source="BBC Business"),
        _make_article("https://music/", source="natalie.mu"),
    ]
    reg = _FakeRegistry({
        "BBC Business": "business",
        "natalie.mu": "music",
    })
    chosen = select_ai_kamiyama_article(
        target_date=date(2026, 5, 31),
        page3_runner_ups=runner_ups,
        registry=reg,
        eligible_categories=("business",),
        rng=random.Random(0),
        top_n=1,
    )
    _check(
        "g3 registry + eligible で source 名から category 解決",
        chosen is not None and chosen["url"] == "https://biz/",
    )


# ---------------------------------------------------------------------------
# (h) 連続日重複の自動回避 — 紙面 fixture を 2 日連続変えれば別 URL
# ---------------------------------------------------------------------------

def test_consecutive_days_pick_different_urls_when_paper_changes():
    """紙面が日ごとに変われば AIかみやま は別 URL を選ぶ.

    5/29-5/30 で同一 BBC URL (czx2qll4rlyo) を連続表示した事象の対策。本テストは
    候補プールが日ごとに変わる前提（page3 の確定枠 / runner-up は過去 7 日
    dedup により差し替わる）で、selector が当該日プールに閉じていることを
    確認する。
    """
    # Day 1: 紙面に「czx2qll4rlyo」記事がある
    day1 = [_make_article("https://bbc.com/czx2qll4rlyo", score=99)]
    chosen_day1 = select_ai_kamiyama_article(
        target_date=date(2026, 5, 29),
        page3_runner_ups=day1,
        rng=random.Random(0),
        top_n=1,
    )

    # Day 2: 過去日 dedup により czx2qll4rlyo は当日候補に出ない。
    day2 = [_make_article("https://bbc.com/new-day2-article", score=99)]
    chosen_day2 = select_ai_kamiyama_article(
        target_date=date(2026, 5, 30),
        page3_runner_ups=day2,
        rng=random.Random(0),
        top_n=1,
    )

    _check(
        "h1 day1 と day2 で別 URL が選ばれる（紙面が変われば自動回避）",
        chosen_day1 is not None and chosen_day2 is not None
        and chosen_day1["url"] != chosen_day2["url"],
        f"day1={chosen_day1['url'] if chosen_day1 else None}, "
        f"day2={chosen_day2['url'] if chosen_day2 else None}",
    )


def main() -> int:
    print("ai_kamiyama_selector tests (C40 第二弾 → C155 で候補プール拡張)")
    print()
    print("(a) build_candidate_pool: Page III 確定枠 + runner-up:")
    test_pool_combines_page3_slots_and_runner_ups()
    test_pool_includes_serendipity_slot()
    test_pool_handles_page3_dict_shape()
    test_pool_empty_when_all_none()
    test_pool_skips_articles_without_url()
    print()
    print("(b) Page I は API 構造から除外:")
    test_no_page_one_parameter()
    print()
    print("(d) URL 重複の順序保持 dedup:")
    test_pool_dedups_same_url_across_sources()
    print()
    print("(e) select_ai_kamiyama_article 動作:")
    test_select_top_n_random_within_pool()
    test_select_score_descending_top1()
    test_select_score_none_treated_as_lowest()
    print()
    print("(f) 候補ゼロ → None:")
    test_select_empty_pool_returns_none()
    test_select_single_candidate_is_chosen()
    print()
    print("(g) category フィルタ（任意、通常 skip）:")
    test_select_no_category_filter_by_default()
    test_select_with_explicit_category_filter()
    test_select_with_registry_lookup()
    print()
    print("(h) 連続日重複の自動回避:")
    test_consecutive_days_pick_different_urls_when_paper_changes()
    print()
    print(f"=== {PASS} passed, {FAIL} failed ===")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
