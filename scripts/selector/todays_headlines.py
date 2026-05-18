"""Today's Headlines 用記事選定（Sprint 7 Phase 2 Step 1, 2026-05-19）.

第2面下段に Today's Headlines セクションを新設するための selector。Page I/III
で採用された記事を除外し、許可ソース（NHK 主要/経済、Yahoo! 経済、BBC、
Economist）から ``final_score`` 上位 N 件を選定する。

設計
----
- Page I pipeline の ``candidates_scored`` を再利用 → 追加 LLM コスト 0
- ソース名は ``sources/business.md`` の H3 から parser が抽出する値と完全一致
  させる（BBC は括弧書きの注記込み）
- description が 100 字を超えるものは末尾「…」で truncate
- Yahoo! のような title-only feed は description が空 → summary を空文字列で返す
  （caller 側で summary 行自体を省略する想定）
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date

# sources/business.md の H3 名と完全一致させる。括弧書きの注記が含まれる場合
# (BBC) はそれも込みで指定する必要がある。Sprint 7 Phase 2 着手時に
# source_registry.build_registry の出力から検証済み (2026-05-19)。
HEADLINES_ALLOWED_SOURCES: tuple[str, ...] = (
    "NHK ニュース 主要",
    "NHK ニュース 経済",
    "Yahoo! ニュース 経済",
    "BBC Business（本紙第1面で稼働中）",
    "The Economist",
)

DEFAULT_HEADLINES_TOP_N: int = 3
DEFAULT_SUMMARY_MAX_CHARS: int = 100


def _extract_article_from_selection(sel: object) -> dict | None:
    """RegionSelection (dataclass) と dict 両形式から article を取り出す."""
    art = getattr(sel, "article", None)
    if art is None and isinstance(sel, Mapping):
        art = sel.get("article")
    return art if isinstance(art, dict) else None


def select_todays_headlines(
    *,
    target_date: date,
    candidates_scored: list[dict],
    page1_selected: list[dict] | None = None,
    page3_selections: Mapping | None = None,
    eligible_sources: tuple[str, ...] | None = None,
    top_n: int = DEFAULT_HEADLINES_TOP_N,
) -> list[dict]:
    """Today's Headlines 用に記事 top_n 件を選定.

    Parameters
    ----------
    target_date :
        対象日（将来の絞り込みに使う想定、現状は使用しない）。
    candidates_scored :
        Stage 2 評価済み候補（Page I pipeline の ``result.candidates_scored``）。
        各 dict は ``url`` ``source_name`` ``final_score`` を持つ想定。
    page1_selected :
        Page I に出る記事リスト（``PipelineResult.selected``）。除外対象。
    page3_selections :
        Page III の RegionSelection 群（``Page3Result.selections``）。除外対象。
    eligible_sources :
        フィルタ対象ソース名タプル。None なら ``HEADLINES_ALLOWED_SOURCES``。
    top_n :
        最大選定件数。default 3。

    Returns
    -------
    list[dict]
        選定された記事リスト（最大 ``top_n`` 件、``final_score`` 降順）。
    """
    if eligible_sources is None:
        eligible_sources = HEADLINES_ALLOWED_SOURCES

    excluded: set[str] = set()
    if page1_selected:
        for art in page1_selected:
            u = (art or {}).get("url")
            if u:
                excluded.add(u)
    if page3_selections:
        for sel in page3_selections.values():
            art = _extract_article_from_selection(sel)
            if art:
                u = art.get("url")
                if u:
                    excluded.add(u)

    pool = [
        a for a in candidates_scored
        if a.get("url")
        and a["url"] not in excluded
        and (a.get("source_name") or "") in eligible_sources
    ]

    def _score(a: dict) -> float:
        s = a.get("final_score")
        return s if isinstance(s, (int, float)) else float("-inf")
    pool.sort(key=_score, reverse=True)
    return pool[:top_n]


def format_summary(
    article: dict, max_chars: int = DEFAULT_SUMMARY_MAX_CHARS
) -> str:
    """description を max_chars 字に truncate。空 description (Yahoo! 等) は空文字列.

    HTML render 側は summary が空文字列なら summary 行自体を省略する想定。
    """
    desc = (article.get("description") or "").strip()
    if not desc:
        return ""
    if len(desc) <= max_chars:
        return desc
    # 末尾「…」で 1 文字分の余裕を取る
    return desc[: max_chars - 1].rstrip() + "…"
