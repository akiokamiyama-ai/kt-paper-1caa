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
# (a) build_candidate_pool: runner-up のみ（C161）
#
# C155: Today's Headlines + Page III + Page IV 学術記事 − serendipity
# C161: **Page III 確定 6 枠を除外**し runner-up のみ。3 面と 5 面に同じ記事が
#       出る事象（C160 観察で 3 日中 2 日）を構造的に断つ。
# ---------------------------------------------------------------------------

def test_pool_is_runner_ups_only():
    page3 = {
        "R1": _RegSel(article=_make_article("https://r1/a")),
        "R4": _RegSel(article=_make_article("https://r4/b")),
        "SER": _RegSel(article=_make_article("https://ser/c")),
    }
    runner_ups = [_make_article("https://ru/x"), _make_article("https://ru/y")]
    pool = build_candidate_pool(
        page3_selections=page3, page3_runner_ups=runner_ups,
    )
    urls = {a["url"] for a in pool}
    _check(
        "a1 候補は runner-up のみ（確定枠は入らない）",
        urls == {"https://ru/x", "https://ru/y"}, f"got {sorted(urls)}",
    )


def test_pool_excludes_serendipity_slot():
    """C161: SER 枠も確定枠なので除外される（C155 では含めていた）."""
    page3 = {"SER": _RegSel(article=_make_article("https://ser/only"))}
    runner_ups = [_make_article("https://ru/1")]
    pool = build_candidate_pool(page3_selections=page3, page3_runner_ups=runner_ups)
    _check(
        "a2 SER 枠は候補に含まれない",
        [a["url"] for a in pool] == ["https://ru/1"],
        f"got {[a['url'] for a in pool]}",
    )


def test_pool_preserves_runner_up_order():
    runner_ups = [_make_article(f"https://ru/{i}") for i in range(4)]
    pool = build_candidate_pool(page3_runner_ups=runner_ups)
    _check(
        "a3 runner-up の順序（final_score 降順）を保つ",
        [a["url"] for a in pool] == [f"https://ru/{i}" for i in range(4)],
    )


def test_pool_empty_when_all_none():
    _check("a4 全引数 None → 空 pool", build_candidate_pool() == [])


def test_pool_skips_articles_without_url():
    runner_ups = [
        _make_article("https://ru/1"),
        {"title": "no url", "source_name": "X"},
        {"url": None, "title": "null url"},
    ]
    pool = build_candidate_pool(page3_runner_ups=runner_ups)
    _check("a5 url 欠落 / None は除外",
           [a["url"] for a in pool] == ["https://ru/1"])


def test_pool_dedups_runner_ups():
    runner_ups = [_make_article("https://dup/"), _make_article("https://dup/"),
                  _make_article("https://ru/2")]
    pool = build_candidate_pool(page3_runner_ups=runner_ups)
    _check("a6 runner-up 内の重複 URL は 1 つに畳む",
           [a["url"] for a in pool] == ["https://dup/", "https://ru/2"],
           f"got {[a['url'] for a in pool]}")


# ---------------------------------------------------------------------------
# (a2) 枯渇時の fallback（C161）
#
# runner-up が 0 件になるのは Page III の fetch が総崩れした異常時のみ。
# そのときは確定枠に戻す（重複記事が出るほうが第5面が白紙になるより良い）。
# ---------------------------------------------------------------------------

def test_fallback_to_confirmed_when_runner_ups_empty():
    page3 = {
        "R1": _RegSel(article=_make_article("https://r1/a")),
        "R6": _RegSel(article=_make_article("https://r6/b")),
    }
    pool = build_candidate_pool(page3_selections=page3, page3_runner_ups=[])
    urls = {a["url"] for a in pool}
    _check("a7 runner-up 0 件 → 確定枠に fallback",
           urls == {"https://r1/a", "https://r6/b"}, f"got {sorted(urls)}")


def test_fallback_also_when_runner_ups_none():
    page3 = {"R1": _RegSel(article=_make_article("https://r1/a"))}
    pool = build_candidate_pool(page3_selections=page3, page3_runner_ups=None)
    _check("a8 runner-up None でも fallback が効く",
           [a["url"] for a in pool] == ["https://r1/a"])


def test_fallback_skips_placeholder_slots():
    page3 = {"R1": _RegSel(article=None), "R6": _RegSel(article=_make_article("https://r6/b"))}
    pool = build_candidate_pool(page3_selections=page3, page3_runner_ups=[])
    _check("a9 fallback でも placeholder 枠は拾わない",
           [a["url"] for a in pool] == ["https://r6/b"])


def test_fallback_not_used_when_runner_ups_present():
    """runner-up が 1 件でもあれば確定枠は混ざらない（fallback は最後の手段）."""
    page3 = {"R1": _RegSel(article=_make_article("https://r1/a"))}
    pool = build_candidate_pool(
        page3_selections=page3, page3_runner_ups=[_make_article("https://ru/1")],
    )
    _check("a10 runner-up が 1 件でもあれば fallback しない",
           [a["url"] for a in pool] == ["https://ru/1"],
           f"got {[a['url'] for a in pool]}")


def test_pool_handles_page3_dict_shape_in_fallback():
    page3 = {"R1": {"article": _make_article("https://d/1")}, "R4": {"article": None}}
    pool = build_candidate_pool(page3_selections=page3, page3_runner_ups=[])
    _check("a11 fallback は page3 dict 形式にも対応",
           [a["url"] for a in pool] == ["https://d/1"])


# ---------------------------------------------------------------------------
# (a3) top_n が runner-up のみで成立すること（C161）
# ---------------------------------------------------------------------------

def test_top_n_satisfied_by_runner_ups_alone():
    """runner-up 20 件想定で top_n=5 が確定枠なしに成立する."""
    runner_ups = [_make_article(f"https://ru/{i}", score=100 - i) for i in range(20)]
    page3 = {"R1": _RegSel(article=_make_article("https://r1/a", score=999))}
    chosen_urls = set()
    for seed in range(40):
        c = select_ai_kamiyama_article(
            target_date=date(2026, 8, 14),
            page3_selections=page3,
            page3_runner_ups=runner_ups,
            rng=random.Random(seed),
            top_n=5,
        )
        chosen_urls.add(c["url"])
    _check("a12 top_n=5 が runner-up だけで成立",
           chosen_urls <= {f"https://ru/{i}" for i in range(5)},
           f"got {sorted(chosen_urls)}")
    _check("a13 score 999 の確定枠は絶対に選ばれない（除外の構造的保証）",
           "https://r1/a" not in chosen_urls)


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
# (d) C161 (2026-08-13): 旧「確定枠と runner-up をまたぐ dedup」テストは削除。
# 確定枠が候補に入らなくなり、両者をまたぐ重複自体が起こり得ない。
# runner-up 内の dedup は (a6) が検証する。
# ---------------------------------------------------------------------------


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
    print("(a) build_candidate_pool: runner-up のみ (C161):")
    test_pool_is_runner_ups_only()
    test_pool_excludes_serendipity_slot()
    test_pool_preserves_runner_up_order()
    test_pool_empty_when_all_none()
    test_pool_skips_articles_without_url()
    test_pool_dedups_runner_ups()
    print()
    print("(a2) 枯渇時の fallback (C161):")
    test_fallback_to_confirmed_when_runner_ups_empty()
    test_fallback_also_when_runner_ups_none()
    test_fallback_skips_placeholder_slots()
    test_fallback_not_used_when_runner_ups_present()
    test_pool_handles_page3_dict_shape_in_fallback()
    print()
    print("(a3) top_n が runner-up のみで成立:")
    test_top_n_satisfied_by_runner_ups_alone()
    print()
    print("(b) Page I は API 構造から除外:")
    test_no_page_one_parameter()
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
