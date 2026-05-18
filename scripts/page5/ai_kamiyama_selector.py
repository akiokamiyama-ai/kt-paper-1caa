"""AIかみやま 専用の記事選定（Sprint 7 Phase 1 Step 1, 2026-05-18）.

Sprint 7 で第5面を「上：serendipity / 下：AIかみやま column」の上下分離構造
に再設計するための前提。AIかみやま のコメント対象記事を、serendipity 記事
ではなく独立に選定する。

設計思想
--------
- serendipity（既存）= 神山さんが「普段読まない領域」（academic / books /
  culture / music / outdoor）の発見
- AIかみやま（新）= 神山さんの「関心領域も含む」全体から、Page I/III/IV +
  serendipity 採用済みを除いた残りに対する一筆。重複を構造的に回避する。

候補プール
----------
``candidates_scored``（Page I pipeline で Stage 2 評価済み記事）を再利用。
Stage 2 LLM コストはゼロで、品質スコア (final_score) も付与済み。

選定アルゴリズム
----------------
1. ``excluded_urls`` (Page I/III/IV/serendipity の採用 URL) を除外
2. ``registry`` + ``eligible_categories`` で category フィルタ（両方与えられた
   場合のみ。テスト時は registry=None で skip 可能）
3. ``final_score`` で降順ソート
4. 上位 ``top_n`` 件から ``rng.choice`` で 1 本選定（tie-break のランダム性）
5. 候補ゼロなら ``None`` を返す（caller 側で fallback）

Phase 1 では「Page III/IV と URL 重複しない」が主目的。Phase 3 で 1 面テーマ
無関係判定 LLM call (``tag="page5.theme_check"``) を追加予定。
"""

from __future__ import annotations

import random
from datetime import date
from typing import Any

from ..selector.source_registry import SourceRegistry


# Sprint 7 Phase 1 暫定の category 制約。Page III の 6 領域 + Page IV 学術記事
# の母集団を表現。Phase 2/3 で運用観察しつつ調整する。
# 神山さんの「読む」関心領域を広めに取り、serendipity 5 種（academic/books/
# culture/music/outdoor）との差別化は除外 URL で担保する。
AI_KAMIYAMA_CATEGORIES: tuple[str, ...] = (
    "business",
    "geopolitics",
    "academic",
    "books",
    "culture",
)

# 上位 N 件から random 選定。score 1 位固定だと毎日同じ source 系統に偏る
# 可能性があり、tie-break のランダム性で多様性を確保する。
DEFAULT_TOP_N: int = 5


def collect_used_urls(
    *,
    page1_selected: list[dict] | None = None,
    page3_selections: dict | None = None,
    page4_articles: list[dict] | None = None,
    serendipity_article: dict | None = None,
) -> set[str]:
    """Page I/III/IV/serendipity の採用 URL を集計.

    Parameters
    ----------
    page1_selected :
        ``PipelineResult.selected`` (Page I に出る記事 N 本)。
    page3_selections :
        ``Page3Result.selections`` (dict[str, RegionSelection])。
        RegionSelection は dataclass で ``.article`` を持つ。
    page4_articles :
        ``page4_telemetry["articles_result"]["articles"]`` (学術記事 3 本)。
    serendipity_article :
        ``serendipity["article"]`` (上段 serendipity の 1 本)。

    Returns
    -------
    set[str]
        全採用 URL の集合。None や空 URL は除外。
    """
    urls: set[str] = set()
    if page1_selected:
        for art in page1_selected:
            u = (art or {}).get("url")
            if u:
                urls.add(u)
    if page3_selections:
        for _region, sel in page3_selections.items():
            # RegionSelection (dataclass) or dict 両対応
            art = getattr(sel, "article", None)
            if art is None and isinstance(sel, dict):
                art = sel.get("article")
            if art:
                u = (art or {}).get("url")
                if u:
                    urls.add(u)
    if page4_articles:
        for art in page4_articles:
            u = (art or {}).get("url")
            if u:
                urls.add(u)
    if serendipity_article:
        u = serendipity_article.get("url")
        if u:
            urls.add(u)
    return urls


def _article_category(
    article: dict, registry: SourceRegistry | None
) -> str | None:
    """article の source_name から category を引く。article に既に
    ``category`` フィールドがあれば優先（page4 等は事前付与）.
    """
    cat = article.get("category")
    if cat:
        # source.category は "companies:Cocolomi" のように prefix を持つ
        # 場合がある。base category（":" 前）に揃える。
        return cat.split(":", 1)[0]
    if registry is None:
        return None
    name = article.get("source_name") or ""
    src = registry.sources_by_name.get(name)
    if src is None:
        return None
    return src.category.split(":", 1)[0]


def select_ai_kamiyama_article(
    *,
    target_date: date,
    excluded_urls: set[str],
    candidates_scored: list[dict],
    registry: SourceRegistry | None = None,
    eligible_categories: tuple[str, ...] | None = None,
    rng: random.Random | None = None,
    top_n: int = DEFAULT_TOP_N,
) -> dict | None:
    """AIかみやま 専用の記事選定。

    Parameters
    ----------
    target_date :
        対象日（将来 Phase 3 のテーマ判定で使う想定、現状は使用しない）。
    excluded_urls :
        Page I/III/IV/serendipity で既に採用された URL の集合。
    candidates_scored :
        Stage 2 評価済み候補（Page I pipeline の ``result.candidates_scored``）。
        各 dict は最低限 ``url`` ``final_score`` を持つ想定。
    registry :
        source category 解決用。``None`` の場合は category フィルタを skip。
    eligible_categories :
        category フィルタ対象。``None`` または空タプルなら全 category 許可。
        通常は ``AI_KAMIYAMA_CATEGORIES`` を渡す。
    rng :
        テスト用の random.Random。None ならグローバル random を使う。
    top_n :
        上位何件から random 選定するか。default ``DEFAULT_TOP_N=5``。

    Returns
    -------
    dict | None
        選ばれた article dict、または候補ゼロで None。
    """
    if not candidates_scored:
        return None

    if rng is None:
        rng = random.Random()

    # 1) excluded_urls 除外
    pool = [
        a for a in candidates_scored
        if a.get("url") and a["url"] not in excluded_urls
    ]
    if not pool:
        return None

    # 2) category フィルタ（registry + eligible_categories の両方与えられた場合のみ）
    if eligible_categories:
        filtered = [
            a for a in pool
            if _article_category(a, registry) in eligible_categories
        ]
        if filtered:
            pool = filtered
        # filtered が空ならフィルタ無視で pool 全体を残す（候補枯渇を避ける）

    # 3) final_score で降順ソート（None は最下位扱い）
    def _score(a: dict) -> float:
        s = a.get("final_score")
        return s if isinstance(s, (int, float)) else float("-inf")
    pool.sort(key=_score, reverse=True)

    # 4) 上位 top_n から random 選定
    n = min(top_n, len(pool))
    if n <= 0:
        return None
    return rng.choice(pool[:n])
