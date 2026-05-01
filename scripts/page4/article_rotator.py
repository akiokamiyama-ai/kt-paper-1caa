"""Page IV academic articles — 3 本ローテーション (3-day cycle).

Strategy
--------
1. Load logs/page4_rotation.json
2. If ``expires_on`` >= today: reuse the cached pool (refetch URLs to render)
3. Otherwise regenerate:
   a. Fetch academic.md + books.md High+Medium
   b. Pass through Stage 1 (description-length / podcast filters etc)
   c. Restrict books.md sources to humanities imprints (HUMANITIES_IMPRINTS).
      Natural-science nonfiction stays out — that's Page III R6's territory.
   d. Pass through Stage 2 + Stage 3 (with optional Stage 2 reuse via
      ``pre_evaluated``)
   e. Filter out URLs displayed on page4 in past HISTORY_LOOKBACK_DAYS (30) days
   f. Pick top N=3 by ``final_score``
   g. Persist to logs/page4_rotation.json with ``expires_on = today + 3 days``
"""

from __future__ import annotations

import json
import re
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from ..fetch import run as fetch_run
from ..selector.dedup_filter import (
    filter_recently_displayed,
    load_recently_displayed_urls,
)
from ..selector.source_registry import SourceRegistry, build_registry
from ..selector.stage1 import run_stage1
from ..selector.stage2 import run_stage2
from ..selector.stage3 import integrate_scores

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SOURCES_DIR = PROJECT_ROOT / "sources"
LOG_DIR = PROJECT_ROOT / "logs"
ROTATION_PATH = LOG_DIR / "page4_rotation.json"

ROTATION_DAYS: int = 3
HISTORY_LOOKBACK_DAYS: int = 30
N_ARTICLES: int = 3
PER_FETCH_LIMIT: int = 8

# books.md は基本「自然科学ノンフ → page3 R6」「人文系 → page4」で分業。
# books.md にはサブカテゴリのメタデータがないため、source_name の
# 部分一致で人文系インプリントを判定する（in 演算子）。
HUMANITIES_IMPRINTS: tuple[str, ...] = (
    # 学術系出版社・人文系
    "岩波",           # 岩波書店 / 岩波新書 / 岩波現代文庫 / 岩波文庫 すべてカバー
    "春秋社",
    "青土社",
    "みすず書房",
    "白水社",
    "勁草書房",
    "ナカニシヤ出版",
    # 文庫・新書（学術・人文系インプリント）
    "ちくま学芸文庫",
    "ちくま新書",
    "ちくまプリマー新書",
    "講談社学術文庫",
    "講談社現代新書",
    "講談社選書メチエ",
    "集英社新書",
    "角川選書",
    "角川ソフィア文庫",
    "中公新書",
    "中公叢書",
)

# 意図的な除外：
# - ブルーバックス（科学新書）→ page3 R6 の自然科学枠
# - 角川文庫（小説）→ page5 leisure
# - マンガ・ラノベ系インプリント → 第3〜6面のいずれにも該当せず


_HTML_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")


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
# HUMANITIES filter
# ---------------------------------------------------------------------------

def is_humanities(publisher_or_imprint: str | None) -> bool:
    """Return True if the source name contains any humanities imprint key."""
    if not publisher_or_imprint:
        return False
    return any(key in publisher_or_imprint for key in HUMANITIES_IMPRINTS)


# ---------------------------------------------------------------------------
# Rotation log persistence
# ---------------------------------------------------------------------------

def load_rotation(*, path: Path | None = None) -> dict:
    p = path or ROTATION_PATH
    if not p.exists():
        return {"pool": [], "expires_on": None, "generated_on": None}
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {"pool": [], "expires_on": None, "generated_on": None}


def save_rotation(data: dict, *, path: Path | None = None) -> None:
    p = path or ROTATION_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def is_pool_active(rotation: dict, today: date) -> bool:
    """True iff the cached pool is still in its rotation window AND non-empty.

    v1.1（2026-05-02 fix）: 以前は ``expires_on >= today`` のみ判定していたため
    pool=[] + 将来 expires_on のとき「active と判定 → cache rebuild branch
    を試行 → 0件 → fall through で regenerate」という二重 fetch を引き起
    こしていた。空 pool は invalidate 扱いに統一。
    """
    pool = rotation.get("pool")
    if not pool:
        return False
    exp = rotation.get("expires_on")
    if not exp:
        return False
    try:
        exp_d = date.fromisoformat(exp)
    except (ValueError, TypeError):
        return False
    return exp_d >= today


# ---------------------------------------------------------------------------
# Fetch + Stage1+2+3 pipeline (humanities-only)
# ---------------------------------------------------------------------------

def _fetch_and_score_humanities(
    *,
    pre_evaluated: dict[str, dict] | None = None,
    registry: SourceRegistry | None = None,
) -> tuple[list[dict], float]:
    """Fetch academic + books High/Medium, run Stage 1+2+3, restrict to
    humanities (academic.md all + books.md humanities imprints).

    Returns (scored_articles, llm_cost_usd).
    """
    if registry is None:
        registry = build_registry(SOURCES_DIR)

    raw: list[Any] = []
    for cat in ("academic", "books"):
        for pri in ("high", "medium"):
            try:
                summary = fetch_run(
                    category=cat, priority=pri, limit=PER_FETCH_LIMIT,
                    no_dedupe=True, write_log=False,
                )
                raw.extend(summary.get("articles", []))
            except Exception as e:
                print(
                    f"[page4] fetch_run({cat}, {pri}) failed: "
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

    # Restrict to humanities scope.
    humanities: list[dict] = []
    for art in surviving:
        name = art.get("source_name") or ""
        src = registry.sources_by_name.get(name)
        cat = src.category if src else None
        art["category"] = cat
        if cat == "academic":
            humanities.append(art)
        elif cat == "books":
            if is_humanities(name):
                humanities.append(art)
        # else: out of scope (shouldn't happen given our fetch)

    if not humanities:
        return [], 0.0

    # Stage 2 reuse via pre_evaluated.
    cached: list[dict] = []
    uncached: list[dict] = []
    for art in humanities:
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

    return cached, cost


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def _rebuild_from_pool(
    rotation: dict,
    *,
    pre_evaluated: dict[str, dict] | None,
    registry: SourceRegistry | None,
) -> dict:
    """Cached path: fetch once, filter to pool URLs, preserve pool order.

    Returns the same dict shape as ``get_today_articles``. If the cached
    URLs are no longer fetchable, ``articles`` may be empty — caller can
    detect this and fall through to ``_generate_new_pool``.
    """
    articles, cost = _fetch_and_score_humanities(
        pre_evaluated=pre_evaluated, registry=registry,
    )
    url_set = set(rotation.get("pool", []))
    chosen = [a for a in articles if a.get("url") in url_set]
    order = {url: i for i, url in enumerate(rotation.get("pool", []))}
    chosen.sort(key=lambda a: order.get(a.get("url"), 1_000_000))
    return {
        "articles": chosen,
        "from_cache": True,
        "cost_usd": cost,
        "rotation": rotation,
    }


def _generate_new_pool(
    target_date: date,
    *,
    pre_evaluated: dict[str, dict] | None,
    registry: SourceRegistry | None,
    persist: bool,
) -> dict:
    """Regeneration path: fetch once, dedup, sort, top-N, save rotation."""
    articles, cost = _fetch_and_score_humanities(
        pre_evaluated=pre_evaluated, registry=registry,
    )

    past_urls = load_recently_displayed_urls(
        days_back=HISTORY_LOOKBACK_DAYS, page="page4", until_date=target_date,
    )
    if past_urls:
        before = len(articles)
        articles = filter_recently_displayed(articles, past_urls)
        print(
            f"[page4] dedup: removed {before - len(articles)}/{before} "
            f"already shown in past {HISTORY_LOOKBACK_DAYS} days",
            file=sys.stderr,
        )

    articles.sort(key=lambda a: a.get("final_score", 0.0), reverse=True)
    chosen = articles[:N_ARTICLES]

    new_rotation = {
        "pool": [a.get("url") for a in chosen if a.get("url")],
        "expires_on": (target_date + timedelta(days=ROTATION_DAYS)).isoformat(),
        "generated_on": target_date.isoformat(),
    }
    if persist:
        save_rotation(new_rotation)

    return {
        "articles": chosen,
        "from_cache": False,
        "cost_usd": cost,
        "rotation": new_rotation,
    }


def get_today_articles(
    target_date: date | None = None,
    *,
    pre_evaluated: dict[str, dict] | None = None,
    rotation: dict | None = None,
    registry: SourceRegistry | None = None,
    persist: bool = True,
) -> dict:
    """Return today's 3 articles + cost telemetry.

    Dispatches between ``_rebuild_from_pool`` (cached, 1 fetch) and
    ``_generate_new_pool`` (regenerate, 1 fetch). v1.1 (2026-05-02) で
    ``is_pool_active`` を「expiry AND pool 非空」に強化したことで、
    通常パスでは fetch が一度しか走らないことを保証する。

    Returns::

        {
            "articles": [art1, art2, art3],
            "from_cache": bool,
            "cost_usd": float,
            "rotation": {...},
        }
    """
    if target_date is None:
        target_date = date.today()
    if rotation is None:
        rotation = load_rotation()

    if is_pool_active(rotation, target_date):
        result = _rebuild_from_pool(
            rotation, pre_evaluated=pre_evaluated, registry=registry,
        )
        if result["articles"]:
            return result
        # Cold cache invalidation: rotation log says active but URLs are
        # no longer fetchable (sources rotated, deleted, etc.). Falls
        # through to regenerate — fetch fires a 2nd time only in this
        # rare path. Logged so it's visible.
        print(
            f"[page4] cached pool {rotation.get('pool')} no longer fetchable, "
            "regenerating",
            file=sys.stderr,
        )

    return _generate_new_pool(
        target_date,
        pre_evaluated=pre_evaluated, registry=registry, persist=persist,
    )
