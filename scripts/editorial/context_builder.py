"""Build the Tribune editorial-postscript context from per-page telemetry.

The editorial LLM receives a JSON summary of the day's paper. This module
extracts only the "what got selected" facts (titles + sources + categories)
from each page's telemetry, deliberately omitting body text and scores so
the LLM focuses on cross-page structure rather than parroting article copy.

Sprint 4 Phase 3 (2026-05-03).
"""

from __future__ import annotations


# Page III の slot ラベル（context 用、order を保つ）。
# C155 (Sprint 13, 2026-08-10): R2 廃止、6 枠目に SER（セレンディピティ）。
# selector.page3 を import せずローカル定義しているのは、editorial が
# selector 層に依存しないようにするため（既存方針を踏襲）。
PAGE3_DISPLAY_SLOTS: tuple[str, ...] = (
    "R1", "R3", "R4", "R5", "R6", "SER",
)

# Page II 表示順（Cocolomi → Human Energy → Web-Repo）
PAGE2_COMPANY_ORDER: tuple[str, ...] = ("cocolomi", "human_energy", "web_repo")

PAGE2_COMPANY_DISPLAY_NAMES: dict[str, str] = {
    "cocolomi":     "こころみ",
    "human_energy": "ヒューマンエナジー",
    "web_repo":     "ウェブリポ",
}


def _safe_str(value, default: str = "") -> str:
    """Return str(value) if value is not None, else default."""
    if value is None:
        return default
    if isinstance(value, str):
        return value
    return str(value)


def _extract_title_source(article: dict | None) -> dict:
    """Pull (title, source) out of an article dict; safe on None / missing keys."""
    if not article:
        return {"title": "", "source": ""}
    return {
        "title": _safe_str(article.get("title")),
        "source": _safe_str(article.get("source_name")),
    }


def build_editorial_context(
    *,
    page_one_selected: list[dict] | None = None,
    page_two_selections: dict | None = None,
    page_three_selections: dict | None = None,
    page_four_telemetry: dict | None = None,
    page_five_telemetry: dict | None = None,
    page_six_telemetry: dict | None = None,
) -> dict:
    """Assemble the structured context the editorial LLM consumes.

    All inputs are optional — pages skipped via --skip-pageN simply contribute
    empty entries. The output is a JSON-serialisable dict.

    Parameters mirror the regen_front_page_v2 main-flow telemetry shape:
      * page_one_selected: C155 以降は常に None（Page I は週次 essay で、
        editorial の参照対象から外している。C45 D2 の恒久化）
      * page_two_selections: dict[company_key → CompanySelection]
      * page_three_selections: dict[slot → RegionSelection]（5 領域 + SER）
      * page_four_telemetry: {"concept": ..., "essay_result": ...}
      * page_five_telemetry: {"ai_article": ..., "summary": ..., "column": ...}
      * page_six_telemetry: {"books": ..., "music": ..., "outdoor": ..., "cooking": ...}

    C155 (Sprint 13, 2026-08-10) での変更:
      * page4_articles（学術ニュース 3 本）を廃止
      * page5_serendipity → page5_reference（一筆の参照記事）に置換
    """
    out: dict = {}

    # ----- Page I -----
    p1 = list(page_one_selected or [])
    out["page1_top"] = _extract_title_source(p1[0] if p1 else None)
    out["page1_secondaries"] = [
        _extract_title_source(a) for a in p1[1:4]
    ]

    # ----- Page II -----
    p2_list: list[dict] = []
    sels = page_two_selections or {}
    for key in PAGE2_COMPANY_ORDER:
        sel = sels.get(key)
        article = getattr(sel, "article", None) if sel is not None else None
        info = _extract_title_source(article)
        info["company"] = PAGE2_COMPANY_DISPLAY_NAMES.get(key, key)
        p2_list.append(info)
    out["page2"] = p2_list

    # ----- Page III -----
    p3_list: list[dict] = []
    p3sels = page_three_selections or {}
    for region in PAGE3_DISPLAY_SLOTS:
        sel = p3sels.get(region)
        article = getattr(sel, "article", None) if sel is not None else None
        info = _extract_title_source(article)
        info["region"] = region
        p3_list.append(info)
    out["page3"] = p3_list

    # ----- Page IV -----
    # C155: 学術ニュース枠を廃止し、概念のみの面になった。
    p4_concept = ""
    if page_four_telemetry:
        concept = page_four_telemetry.get("concept") or {}
        p4_concept = _safe_str(concept.get("name_ja")) or _safe_str(concept.get("id"))
    out["page4_concept"] = p4_concept

    # ----- Page V -----
    # C155: serendipity 枠は Page III へ移設。第5面は一筆とその参照記事のみ。
    p5_reference: dict = {"title": "", "source": "", "category": ""}
    p5_column_title = ""
    if page_five_telemetry:
        article = page_five_telemetry.get("ai_article") or {}
        p5_reference = {
            "title": _safe_str(article.get("title")),
            "source": _safe_str(article.get("source_name")),
            "category": _safe_str(article.get("category")),
        }
        col = page_five_telemetry.get("column") or {}
        p5_column_title = _safe_str(col.get("column_title"))
    out["page5_reference"] = p5_reference
    out["page5_aikamiyama_column_title"] = p5_column_title

    # ----- Page VI -----
    p6_columns: dict[str, str] = {}
    if page_six_telemetry:
        for area in ("books", "music", "outdoor", "cooking"):
            entry = page_six_telemetry.get(area) or {}
            p6_columns[area] = _safe_str(entry.get("column_title"))
    else:
        p6_columns = {"books": "", "music": "", "outdoor": "", "cooking": ""}
    out["page6_columns"] = p6_columns

    return out
