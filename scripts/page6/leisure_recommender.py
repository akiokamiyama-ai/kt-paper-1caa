"""第6面 Leisure: 読書 / 音楽 / アウトドア 共通の RAG + コラム生成。

Sprint 4 layout swap で旧 page5 から移動（実装は Sprint 3 Step C）。

Pipeline (per area = books | music | outdoor):

1. ``{area}.md`` の High+Medium から記事候補取得 (default_fetcher)
2. Stage 1（機械フィルタ：description 30字以上 / podcast 除外 等）
3. Stage 2（美意識 LLM）→ Stage 3（final_score 統合）
4. dedup：過去 N=30 日に page6 で表示済の URL を除外
5. final_score 上位 1 本を選定
6. 候補ゼロ：``is_fallback=True``、placeholder dict を返す
7. LLM コラム生成（領域別 EVAL_GUIDE を system に注入）
8. JSON parse 失敗 / 空応答 → description fallback
"""

from __future__ import annotations

import json
import re
import sys
from datetime import date
from pathlib import Path

from ..lib import llm
from ..selector.dedup_filter import (
    filter_recently_displayed,
    load_recently_displayed_urls,
)
from ..selector.source_registry import SourceRegistry, build_registry
from ..selector.stage1 import run_stage1
from ..selector.stage2 import run_stage2
from ..selector.stage3 import integrate_scores
from .prompts import (
    AREA_LABEL_JA,
    COLUMN_PROMPT_TEMPLATE,
    EVAL_GUIDE_BY_AREA,
    FOCUS_WORK_FORMAT_BY_AREA,
    INTEREST_SUMMARY,
    LEISURE_COLUMN_SYSTEM,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SOURCES_DIR = PROJECT_ROOT / "sources"

DEFAULT_MODEL = llm.DEFAULT_MODEL
DEFAULT_MAX_TOKENS = 1500
DEFAULT_TEMPERATURE = 0.7

PER_FETCH_LIMIT: int = 8
HISTORY_LOOKBACK_DAYS: int = 30
SUPPORTED_AREAS: tuple[str, ...] = ("books", "music", "outdoor")

_HTML_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")
_FENCE_RE = re.compile(
    r"^\s*```(?:json)?\s*\n?|\n?```\s*$", re.IGNORECASE | re.MULTILINE
)


def _strip_html_simple(text: str | None) -> str:
    if not text:
        return ""
    no_tags = _HTML_TAG_RE.sub(" ", text)
    no_entities = (
        no_tags.replace("&nbsp;", " ").replace("&amp;", "&")
        .replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"')
    )
    return _WHITESPACE_RE.sub(" ", no_entities).strip()


# ---------------------------------------------------------------------------
# Books humanities filter (page4 と同じ Boundary を維持)
# ---------------------------------------------------------------------------

# books.md の自然科学ノンフィクションは page3 R6 の領域、
# 人文学術書 (集英社新書プラス, 春秋社, 青土社, Aeon, Marginalian 等) は
# page4 の領域。page5 books は **小説・ジャンル文学・漫画・文芸誌** を取る。
# books.md カテゴリのうち以下の section ソースは page5 で扱わない：
BOOKS_EXCLUDE_FOR_PAGE5: tuple[str, ...] = (
    # 自然科学ノンフ → page3 R6
    "Quanta Magazine", "Nautilus", "日経サイエンス",
    # 人文・思想 → page4
    "The Marginalian", "Aeon",
    "集英社新書プラス", "春秋社", "青土社",
)


def _belongs_to_area(article: dict, area: str) -> bool:
    """Whether this article belongs to ``area`` for page5 selection.

    For ``books``: filters out the page3-R6 / page4 sources to keep page5
    focused on novels / genre fiction / manga / literary magazines.
    Other areas: trust the source.category match.
    """
    if area != "books":
        return True
    name = article.get("source_name") or ""
    if any(excl in name for excl in BOOKS_EXCLUDE_FOR_PAGE5):
        return False
    return True


# ---------------------------------------------------------------------------
# Fetch + score for one area
# ---------------------------------------------------------------------------

def _fetch_and_score_area(
    area: str,
    *,
    pre_evaluated: dict[str, dict] | None = None,
    registry: SourceRegistry | None = None,
) -> tuple[list[dict], float]:
    """Fetch {area}.md High+Medium, run Stage 1+2+3.

    Returns (scored_articles, llm_cost_usd). Articles filtered to area
    via _belongs_to_area().
    """
    from ..fetch import run as fetch_run

    if area not in SUPPORTED_AREAS:
        raise ValueError(f"unsupported area: {area!r}")

    if registry is None:
        registry = build_registry(SOURCES_DIR)

    raw = []
    for pri in ("high", "medium"):
        try:
            summary = fetch_run(
                category=area, priority=pri, limit=PER_FETCH_LIMIT,
                no_dedupe=True, write_log=False,
            )
            raw.extend(summary.get("articles", []))
        except Exception as e:
            print(
                f"[page5] fetch_run({area}, {pri}) failed: "
                f"{type(e).__name__}: {e}",
                file=sys.stderr,
            )

    seen_urls: set[str] = set()
    pipeline_dicts: list[dict] = []
    for a in raw:
        url = a.link or ""
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        body = "\n".join(a.body_paragraphs) if a.body_paragraphs else ""
        pipeline_dicts.append({
            "url": url,
            "title": a.title,
            "description": _strip_html_simple(a.description),
            "body": _strip_html_simple(body),
            "source_name": a.source_name,
            "source_url": None,
            "pub_date": a.pub_date.isoformat() if a.pub_date else None,
        })

    s1_out = run_stage1(pipeline_dicts)
    surviving = [x for x in s1_out if not x.get("is_excluded")]
    if not surviving:
        return [], 0.0

    # Filter to page5 area (mostly relevant for books)
    surviving = [a for a in surviving if _belongs_to_area(a, area)]
    if not surviving:
        return [], 0.0

    # Stage 2 with pre_evaluated reuse
    cached: list[dict] = []
    uncached: list[dict] = []
    for art in surviving:
        url = art.get("url")
        if url and pre_evaluated and url in pre_evaluated:
            merged = dict(art)
            merged.update(pre_evaluated[url])
            cached.append(merged)
        else:
            uncached.append(art)

    cost = 0.0
    if uncached:
        s2 = run_stage2(uncached)
        cost += s2.cost_usd
        integrate_scores(s2.evaluations_by_url)
        by_url = s2.evaluations_by_url
        for art in uncached:
            url = art.get("url")
            if url and url in by_url:
                art.update(by_url[url])
                cached.append(art)

    # Attach category
    for art in cached:
        if not art.get("category"):
            name = art.get("source_name")
            if name:
                src = registry.sources_by_name.get(name)
                if src:
                    art["category"] = src.category

    return cached, cost


# ---------------------------------------------------------------------------
# Column generation (LLM)
# ---------------------------------------------------------------------------

def _build_column_system(area: str) -> str:
    """system = LEISURE_COLUMN_SYSTEM + 領域別 EVAL_GUIDE."""
    guide = EVAL_GUIDE_BY_AREA.get(area, "")
    return LEISURE_COLUMN_SYSTEM + "\n\n" + guide


def _build_column_user(article: dict, area: str) -> str:
    title = (article.get("title") or "").strip()
    source = (article.get("source_name") or "").strip()
    pub_date = (article.get("pub_date") or "").strip() or "(日付不明)"
    description = (article.get("description") or "").strip()
    return COLUMN_PROMPT_TEMPLATE.format(
        area_label=AREA_LABEL_JA.get(area, area),
        title=title, source=source, pub_date=pub_date,
        description=description,
        interest_summary=INTEREST_SUMMARY.get(area, ""),
        focus_work_format=FOCUS_WORK_FORMAT_BY_AREA.get(area, ""),
    )


def _parse_column_response(raw_text: str) -> tuple[dict | None, str | None]:
    if not raw_text:
        return None, "empty_response"
    text = _FENCE_RE.sub("", raw_text).strip()
    if not text.startswith("{"):
        idx = text.find("{")
        if idx < 0:
            return None, "no_json_object_found"
        text = text[idx:]
    end = text.rfind("}")
    if end >= 0:
        text = text[: end + 1]
    try:
        return json.loads(text), None
    except json.JSONDecodeError as e:
        return None, f"json_decode_error: {e.msg}"


def _description_fallback(article: dict) -> dict:
    """When LLM fails: use article description as the column body."""
    desc = (article.get("description") or "").strip()
    title = (article.get("title") or "").strip()
    body = desc[:200] if desc else "（本文取得失敗）"
    column_title = title[:20] if title else "本日の1本"
    return {
        "column_title": column_title,
        # Sprint 5 task #4: focus_work は LLM 生成のため fallback では空
        # （HTML 側で空文字列なら <p class="focus-work"> を出さない）。
        "focus_work": "",
        "column_body": body,
    }


def _generate_column(area: str, article: dict) -> tuple[dict, float, bool]:
    """LLM call. Returns (parsed, cost_usd, is_fallback)."""
    system = _build_column_system(area)
    user = _build_column_user(article, area)
    try:
        response = llm.call_claude_with_retry(
            system=system,
            user=user,
            model=DEFAULT_MODEL,
            max_tokens=DEFAULT_MAX_TOKENS,
            cache_system=True,
        )
        cost = response.cost_usd
        parsed, err = _parse_column_response(response.text)
        if parsed is None or not isinstance(parsed.get("column_title"), str) \
                or not isinstance(parsed.get("column_body"), str):
            print(
                f"[page5/{area}] WARN: parse failed ({err}), description fallback",
                file=sys.stderr,
            )
            return _description_fallback(article), cost, True
        # Sprint 5 task #4: focus_work は新規追加フィールド。LLM が出力しないか
        # 型不正な場合は空文字列扱い（HTML 側で <p> を省略するため fallback でも
        # 紙面構造は壊れない）。
        focus_work_raw = parsed.get("focus_work", "")
        focus_work = focus_work_raw.strip() if isinstance(focus_work_raw, str) else ""
        return {
            "column_title": parsed["column_title"].strip(),
            "focus_work": focus_work,
            "column_body": parsed["column_body"].strip(),
        }, cost, False
    except Exception as e:
        print(
            f"[page5/{area}] WARN: LLM failed ({type(e).__name__}: "
            f"{llm.redact_key(str(e))[:200]}), description fallback",
            file=sys.stderr,
        )
        return _description_fallback(article), 0.0, True


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def _placeholder_result(area: str, fallback_reason: str) -> dict:
    return {
        "area": area,
        "article": None,
        "column_title": "本日該当なし",
        "column_body": "（明日の更新をお待ちください）",
        "is_fallback": True,
        "cost_usd": 0.0,
        "fallback_reason": fallback_reason,
    }


def recommend_for_area(
    area: str,
    *,
    target_date: date | None = None,
    pre_evaluated: dict[str, dict] | None = None,
    registry: SourceRegistry | None = None,
) -> dict:
    """Run the full pipeline for one area; return a dict for page5 rendering.

    Returns::

        {
            "area": str,
            "article": {url, title, source_name, pub_date, description, ...} | None,
            "column_title": str,
            "column_body": str,
            "is_fallback": bool,
            "cost_usd": float,
            "fallback_reason": str | None,
        }
    """
    if area not in SUPPORTED_AREAS:
        raise ValueError(f"unsupported area: {area!r}")
    if target_date is None:
        target_date = date.today()

    # 1〜3) Fetch + Stage 1+2+3
    scored, fetch_cost = _fetch_and_score_area(
        area, pre_evaluated=pre_evaluated, registry=registry,
    )
    if not scored:
        return _placeholder_result(area, "no_candidates_after_stage123")

    # 4) Dedup against past 30 days page6 (Sprint 4 layout swap, was page5)
    past_urls = load_recently_displayed_urls(
        days_back=HISTORY_LOOKBACK_DAYS, page="page6", until_date=target_date,
    )
    if past_urls:
        before = len(scored)
        scored = filter_recently_displayed(scored, past_urls)
        removed = before - len(scored)
        if removed:
            print(
                f"[page5/{area}] dedup: removed {removed}/{before} "
                f"already shown in past {HISTORY_LOOKBACK_DAYS} days",
                file=sys.stderr,
            )
    if not scored:
        return _placeholder_result(area, "all_deduped")

    # 5) Top by final_score
    scored.sort(key=lambda a: a.get("final_score", 0.0), reverse=True)
    article = scored[0]

    # 6〜8) LLM column generation with fallback
    column, column_cost, is_fallback = _generate_column(area, article)

    return {
        "area": area,
        "article": article,
        "column_title": column["column_title"],
        "column_body": column["column_body"],
        "is_fallback": is_fallback,
        "cost_usd": fetch_cost + column_cost,
        "fallback_reason": None,
    }
