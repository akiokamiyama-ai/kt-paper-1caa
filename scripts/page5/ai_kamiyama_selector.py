"""AIかみやま 専用の記事選定（Sprint 7 Phase 1 Step 1, 2026-05-18）.

Sprint 7 で第5面を「上：serendipity / 下：AIかみやま column」の上下分離構造
に再設計するための前提。AIかみやま のコメント対象記事を、serendipity 記事
ではなく独立に選定する。

# Sprint 8 C40 第二弾 (2026-05-30) — 設計変更

旧設計（Sprint 7）：
- 候補プール = ``candidates_scored``（Page I pipeline の Stage 2 評価済記事
  数百件）から ``excluded_urls`` (Page I/III/IV/serendipity 採用済) を引いた残り
- 弱点：紙面に出ていない記事を選んでしまい、編集後記（C45 で別途対策）と同じく
  「読者が照合できない引用」が発生。さらに過去日 dedup が無いため 5/29-5/30 で
  同一 BBC URL (czx2qll4rlyo) を連続表示。

新設計（神山案、C40 第二弾）：
- 候補プール = **当日確定紙面の記事のみ**（Page II Today's Headlines + Page III
  R1-R6 + Page IV 学術記事）
- Page I は意図的に除外（v3 swap で essay 形式に置換される or v2 でも editorial
  との整合性のため、C45 D2 と同じ哲学）
- Page V serendipity は AIかみやま と背中合わせなので除外
- 過去日 dedup は不要：当日紙面は他面の dedup（C40 案1+案2 で headlines、page3
  は 7 日、page4 は 30 日）により既に過去重複から保護されている

設計上のメリット
----------------
- 紙面の内的整合性が保たれる（AIかみやま が引く記事は読者が紙面で発見できる）
- 連続日重複が他面 dedup の連動で自動解決
- ロジックが単純化（pre-evaluated 候補プールへの依存が消える）
"""

from __future__ import annotations

import random
from datetime import date
from typing import Any

from ..selector.source_registry import SourceRegistry


# C40 第二弾以降は category フィルタの必要性は薄れた（候補プール自体が紙面確定
# 記事 = 既に編集判断を通過している）。後方互換のため定数は残すが、caller は
# 通常 None を渡してフィルタ無しで使うのが推奨。
AI_KAMIYAMA_CATEGORIES: tuple[str, ...] = (
    "business",
    "geopolitics",
    "academic",
    "books",
    "culture",
)

# 上位 N 件から random 選定。候補プールが小さくなった C40 第二弾でも、
# top_n=5 までは概ね埋まる（Page II headlines 3 + Page III 6 + Page IV 3 = 最大 12）。
DEFAULT_TOP_N: int = 5


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


def _collect_page3_articles(page3_selections: Any | None) -> list[dict]:
    """Page III の RegionSelection 群から非 None article を取り出す.

    RegionSelection は dataclass で ``.article`` を持つ。dict 形式
    ``{"article": {...}}`` にも対応（テスト容易性）。
    """
    out: list[dict] = []
    if not page3_selections:
        return out
    for _region, sel in page3_selections.items():
        art = getattr(sel, "article", None)
        if art is None and isinstance(sel, dict):
            art = sel.get("article")
        if art and isinstance(art, dict):
            out.append(art)
    return out


def build_candidate_pool(
    *,
    page_two_headlines: list[dict] | None = None,
    page3_selections: Any | None = None,
    page4_articles: list[dict] | None = None,
    serendipity_article: dict | None = None,
) -> list[dict]:
    """C40 第二弾の候補プールを構築する.

    当日確定紙面の Page II Today's Headlines + Page III + Page IV 学術記事を
    まとめ、Page V serendipity と URL 衝突したものを除き、URL で順序保持 dedup
    する。Page I は意図的に含めない（C45 D2 と同じ哲学）。

    Parameters
    ----------
    page_two_headlines :
        Today's Headlines に表示される記事のリスト（``select_todays_headlines``
        の戻り値そのまま）。
    page3_selections :
        ``Page3Result.selections`` (dict[str, RegionSelection])。
    page4_articles :
        Page IV 学術記事リスト（``page4_telemetry["articles_result"]["articles"]``）。
        concept 部分（概念解説）は紙面記事ではないため対象外。
    serendipity_article :
        Page V 上段の serendipity 記事（背中合わせ枠なので除外）。

    Returns
    -------
    list[dict]
        URL を持つ candidate article の順序保持リスト。
    """
    pool: list[dict] = []
    if page_two_headlines:
        pool.extend(a for a in page_two_headlines if a and a.get("url"))
    pool.extend(_collect_page3_articles(page3_selections))
    if page4_articles:
        pool.extend(a for a in page4_articles if a and a.get("url"))

    ser_url = (
        (serendipity_article or {}).get("url") if serendipity_article else None
    )

    seen: set[str] = set()
    if ser_url:
        seen.add(ser_url)

    deduped: list[dict] = []
    for a in pool:
        url = a.get("url")
        if not url or url in seen:
            continue
        seen.add(url)
        deduped.append(a)
    return deduped


def select_ai_kamiyama_article(
    *,
    target_date: date,
    page_two_headlines: list[dict] | None = None,
    page3_selections: Any | None = None,
    page4_articles: list[dict] | None = None,
    serendipity_article: dict | None = None,
    registry: SourceRegistry | None = None,
    eligible_categories: tuple[str, ...] | None = None,
    rng: random.Random | None = None,
    top_n: int = DEFAULT_TOP_N,
) -> dict | None:
    """AIかみやま 専用の記事選定（C40 第二弾、2026-05-30）.

    当日確定紙面（Page II Today's Headlines + Page III + Page IV 学術記事）から、
    Page V serendipity を除いた候補プールで選定する。

    Page I は意図的に対象外（C45 D2 と同じ哲学：v3 swap で消えるか、editorial と
    の重複参照を避けるため）。

    Parameters
    ----------
    target_date :
        対象日（将来 Phase 3 のテーマ判定で使う想定、現状は使用しない）。
    page_two_headlines :
        Page II Today's Headlines のリスト（``select_todays_headlines`` 戻り値）。
    page3_selections :
        ``Page3Result.selections`` (dict[str, RegionSelection])。
    page4_articles :
        Page IV 学術記事のリスト（concept は含めない）。
    serendipity_article :
        Page V 上段に出る serendipity 記事（背中合わせ枠なので除外）。
    registry :
        source category 解決用。``None`` の場合は category フィルタを skip。
        C40 第二弾以降、候補プールが既に編集判断を通っているため通常 None で
        十分。
    eligible_categories :
        category フィルタ対象。``None`` または空タプルなら全 category 許可。
        C40 第二弾以降は通常 None で運用するのが推奨。
    rng :
        テスト用の random.Random。None ならグローバル random を使う。
    top_n :
        上位何件から random 選定するか。default ``DEFAULT_TOP_N=5``。

    Returns
    -------
    dict | None
        選ばれた article dict、または候補ゼロで None。
    """
    pool = build_candidate_pool(
        page_two_headlines=page_two_headlines,
        page3_selections=page3_selections,
        page4_articles=page4_articles,
        serendipity_article=serendipity_article,
    )
    if not pool:
        return None

    if rng is None:
        rng = random.Random()

    # Optional category filter（C40 第二弾以降は通常 skip 推奨）
    if eligible_categories:
        filtered = [
            a for a in pool
            if _article_category(a, registry) in eligible_categories
        ]
        if filtered:
            pool = filtered
        # filtered が空ならフィルタ無視で pool 全体を残す（候補枯渇を避ける）

    # final_score で降順ソート（None は最下位扱い）
    def _score(a: dict) -> float:
        s = a.get("final_score")
        return s if isinstance(s, (int, float)) else float("-inf")
    pool.sort(key=_score, reverse=True)

    # 上位 top_n から random 選定
    n = min(top_n, len(pool))
    if n <= 0:
        return None
    return rng.choice(pool[:n])
