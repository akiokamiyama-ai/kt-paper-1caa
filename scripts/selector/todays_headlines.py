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

import sys
import urllib.parse
from collections.abc import Callable, Mapping
from datetime import date

# sources/business.md の H3 名と完全一致させる。括弧書きの注記が含まれる場合
# (BBC) はそれも込みで指定する必要がある。Sprint 7 Phase 2 着手時に
# source_registry.build_registry の出力から検証済み (2026-05-19)。
#
# C75 (Sprint 9, 2026-06-10): SOURCE_NAME_FILTERS と整合させ FT を追加。
# 両者を同じ集合にする方針：page1 candidates に流入させたソースは
# Today's Headlines でも eligible にする。
# C76 (Sprint 9, 2026-06-10): Shincho QUE を追加。QUE は記事ごとに category を
# 動的判定するため、Headlines では国内系（category=business）のみ通す。
# 国際/Foresight 系（category=geopolitics）は page3 R1/R3 へ振り分けされる。
HEADLINES_ALLOWED_SOURCES: tuple[str, ...] = (
    "NHK ニュース 主要",
    "NHK ニュース 経済",
    "Yahoo! ニュース 経済",
    "BBC Business",
    "The Economist",
    "Financial Times（FT）",  # C75: SOURCE_NAME_FILTERS と整合
    "Shincho QUE（新潮QUE）",  # C76: 国内系のみ Headlines 候補に流入
)

# C76 (Sprint 9, 2026-06-10): per-source category 制限。``source_name`` ベース
# allowlist だけでは「QUE の Foresight 国際記事まで Today's Headlines に混入」
# してしまうため、ソースごとに「許可する category」を追加で絞る。QUE のみが
# 動的 category を持つので、現状は QUE 専用エントリ。マッピングは
# ``scripts/lib/drivers/que_shincho.QUE_TRIBUNE_CATEGORY_MAP`` を参照。
HEADLINES_SOURCE_CATEGORY_RESTRICT: dict[str, tuple[str, ...]] = {
    "Shincho QUE（新潮QUE）": ("business",),
}

DEFAULT_HEADLINES_TOP_N: int = 3
# Sprint 7 Phase 2 微調整 (2026-05-20): 5/19 朝刊観察で 100 字では内容が
# ほぼ分からないと神山さん指摘、200 字に拡張。3 記事構成の紙面スペースで許容範囲。
DEFAULT_SUMMARY_MAX_CHARS: int = 200
# C40 (Sprint 8, 2026-05-28): 過去 displayed_urls から headlines URL を除外する
# 窓サイズ。5/27-5/28 で BBC が同 URL のままタイトル更新するパターンを観測。
# PAGE2_DEDUP_DAYS=3 より長め (7) を採用 — 同じ記事を 1 週間以内に 2 回出すのは
# 紙面の鮮度として不適、2 週間以上前の再評価は許容、というバランス。
HEADLINES_DEDUP_DAYS: int = 7


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
    recent_displayed_urls: set[str] | None = None,
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
    recent_displayed_urls :
        過去 ``HEADLINES_DEDUP_DAYS`` 日に headlines として表示された URL の集合
        (C40, Sprint 8, 2026-05-28)。caller が
        ``load_recently_displayed_urls(HEADLINES_DEDUP_DAYS, page="headlines",
        until_date=target_date)`` で算出して渡す。``None`` または空集合なら
        recency dedup を行わない（Sprint 7 までの挙動と等価）。
        BBC 等の URL 不変・タイトル更新パターンへの対策。

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
    if recent_displayed_urls:
        excluded |= recent_displayed_urls

    def _eligible(a: dict) -> bool:
        if not a.get("url") or a["url"] in excluded:
            return False
        src = a.get("source_name") or ""
        if src not in eligible_sources:
            return False
        # C76 (2026-06-10): per-source category 制限。QUE のような動的
        # category を持つソースは、Headlines に流入させたい category のみ通す。
        restrict = HEADLINES_SOURCE_CATEGORY_RESTRICT.get(src)
        if restrict and (a.get("category") or "") not in restrict:
            return False
        return True

    pool = [a for a in candidates_scored if _eligible(a)]

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


# ===========================================================================
# C14 対処 (Sprint 8, 2026-05-20): LLM 要約生成
# ---------------------------------------------------------------------------
# 5/20 朝刊観察で神山さん指摘：RSS description ~100 字では「読めてる感じが
# しない」、200 字程度の実用情報量が欲しい。Step 4 調査で真因判明 —
# BBC/NHK/Economist の RSS は description しか持たず、content:encoded 等の
# 長文フィールドが存在しないため truncate では絶対に 200 字に届かない。
#
# Step A-1 検証結果（4 ソースで本文 fetch を試行）：
#   * BBC      : 記事ページから本文 4,800〜6,700 字をクリーンに抽出可（有効）
#   * NHK      : 記事ページの情報量が RSS description とほぼ同じ ~105 字（無効）
#   * Economist: ペイウォール、HTML に本文が含まれない（無効）
# よって LLM 要約は BBC 記事のみ有効。BBC 以外 / 取得失敗 / LLM 失敗時は
# 必ず format_summary に fallback し、紙面破綻を防ぐ。
# ===========================================================================

LLM_SUMMARY_MODEL: str = "claude-haiku-4-5"
# Phase A (Sprint 8, 2026-06-01): tag を page2.* 規約に揃え、Page II Today's
# Headlines セクションの LLM call であることを明示。
LLM_SUMMARY_TAG: str = "page2.headlines_summary"
# 本文がこの長さ未満なら LLM 要約しても情報が増えないので fallback。
BODY_MIN_CHARS: int = 400
# LLM 出力の暴走防止上限（Sprint 8 C22, 2026-05-23: 目安 250-350 字に
# 引き上げに伴い 300 → 400 へ。350 字目安 + 末尾「…」分の余裕）。
LLM_SUMMARY_MAX_CHARS: int = 400

_SUMMARY_SYSTEM_PROMPT = """あなたは朝刊の編集者です。与えられたニュース記事を、読者が「何の記事か」を即座に理解できるよう、250-350 字目安の日本語で要約してください。

【要約の指針】
- 事実を簡潔に。「誰が・何を・なぜ」を必ず含める
- 解釈・評価・意見は加えない
- 250-350 字目安（240〜360 字を許容範囲とする）
- 要約文のみを出力。前置き・後置き・括弧書き・コードフェンスは不要"""

_SUMMARY_USER_TEMPLATE = """記事タイトル: {title}
ソース: {source}

本文:
{body}"""


def _fetch_bbc_body(url: str, *, max_paragraphs: int = 8) -> str:
    """BBC News 記事ページから本文段落を取得して連結。

    BBC 以外のホスト、または取得失敗時は空文字列を返す（caller が fallback）。
    ``BbcArticleScraper.paragraphs`` は内部でネットワーク例外を握り潰し、
    失敗時は空リストを返す。
    """
    host = urllib.parse.urlparse(url).netloc.lower()
    if not (host == "bbc.com" or host.endswith(".bbc.com")
            or host == "bbc.co.uk" or host.endswith(".bbc.co.uk")):
        return ""
    from ..lib.drivers.html import BbcArticleScraper

    paragraphs = BbcArticleScraper().paragraphs(url, max_paragraphs)
    return " ".join(paragraphs).strip()


def _call_haiku_summary(title: str, source: str, body: str) -> str:
    """記事本文を Haiku で ~200 字要約。tag='page2.headlines_summary' でコスト計上."""
    from ..lib.llm import call_claude_with_retry

    user = _SUMMARY_USER_TEMPLATE.format(
        title=title, source=source, body=body[:2000],
    )
    resp = call_claude_with_retry(
        system=_SUMMARY_SYSTEM_PROMPT,
        user=user,
        model=LLM_SUMMARY_MODEL,
        max_tokens=512,
        tag=LLM_SUMMARY_TAG,
    )
    return resp.text


def generate_summary_with_llm(
    article: dict,
    *,
    body_fetcher: Callable[[str], str] | None = None,
    llm_caller: Callable[[str, str, str], str] | None = None,
) -> str:
    """記事本文を fetch し Haiku で ~200 字要約。失敗時は format_summary に fallback.

    BBC 記事のみ本文取得が有効（Step A-1 検証）。BBC 以外・取得失敗・本文が
    短すぎる・LLM 失敗のいずれでも ``format_summary(article)`` に落ちるため、
    紙面が破綻することはない。

    Parameters
    ----------
    article :
        ``url`` ``title`` ``source_name`` ``description`` を持つ記事 dict。
    body_fetcher :
        ``url -> body`` の本文取得関数。テスト用に差し替え可能。
        None なら :func:`_fetch_bbc_body`。
    llm_caller :
        ``(title, source, body) -> summary`` の要約関数。テスト用に差し替え可能。
        None なら :func:`_call_haiku_summary`。
    """
    fallback = format_summary(article)
    url = (article.get("url") or "").strip()
    if not url:
        return fallback

    fetch = body_fetcher or _fetch_bbc_body
    call = llm_caller or _call_haiku_summary

    try:
        body = fetch(url)
    except Exception as e:  # noqa: BLE001 — どんな失敗でも fallback
        print(
            f"[headlines] body fetch failed ({type(e).__name__}), "
            f"using RSS description: {url[:60]}",
            file=sys.stderr,
        )
        return fallback
    if not body or len(body) < BODY_MIN_CHARS:
        # 本文が取れない（BBC 以外）/ 短すぎる → RSS description のまま。
        return fallback

    try:
        summary = call(
            article.get("title") or "",
            article.get("source_name") or "",
            body,
        )
    except Exception as e:  # noqa: BLE001 — LLM 失敗（cap 超過含む）も fallback
        print(
            f"[headlines] LLM summary failed ({type(e).__name__}), "
            f"using RSS description: {url[:60]}",
            file=sys.stderr,
        )
        return fallback

    summary = (summary or "").strip()
    if not summary:
        return fallback
    # LLM 出力の暴走防止（通常は 200 字前後で収まる）。
    if len(summary) > LLM_SUMMARY_MAX_CHARS:
        summary = summary[: LLM_SUMMARY_MAX_CHARS - 1].rstrip() + "…"
    return summary
