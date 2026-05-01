"""Stage 1 orchestrator: mainstream + blacklist + hard filter.

Accepts either ``Article`` dataclasses (the shape produced by
``scripts.lib.drivers.rss``) or pre-normalized dicts, and returns a list
of dicts with these added fields:

* ``美意識2_score`` — 5 / 3 / 0
* ``美意識4_penalty`` — 0 / -3 / -5
* ``is_excluded`` — bool
* ``exclusion_reason`` — string or None

Stage 1 does not invoke the LLM and does not touch any output files. It is
a pure transform from articles → scored articles, intended to be plumbed
into Stage 2 by a later sprint.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ..lib.source import Article
from . import hard_filter
from .blacklist import load_blacklist, score_blacklist
from .source_registry import SourceRegistry, build_registry

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SOURCES_DIR = PROJECT_ROOT / "sources"
BLACKLIST_PATH = PROJECT_ROOT / "docs" / "blacklist_v1.md"

_HTML_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(s: str | None) -> str:
    if not s:
        return ""
    return _HTML_TAG_RE.sub(" ", s)


def _to_dict(article: Article | dict[str, Any]) -> dict[str, Any]:
    """Normalize an Article dataclass or dict into a working dict.

    For Article inputs we map ``link`` → ``url`` to match the spec naming.
    For dict inputs we copy as-is so the caller's keys are preserved.
    """
    if isinstance(article, dict):
        return dict(article)
    body = "\n".join(article.body_paragraphs) if article.body_paragraphs else ""
    return {
        "url": article.link,
        "title": article.title,
        "description": article.description,
        "body": body,
        "source_name": article.source_name,
        "source_url": None,
        "pub_date": article.pub_date.isoformat() if article.pub_date else None,
    }


def run_stage1(
    articles: list[Article] | list[dict[str, Any]],
    *,
    registry: SourceRegistry | None = None,
    blacklist: list[re.Pattern[str]] | None = None,
) -> list[dict[str, Any]]:
    """Apply Stage 1 mechanical filters; see module docstring for fields."""
    if registry is None:
        registry = build_registry(SOURCES_DIR)
    if blacklist is None:
        blacklist = load_blacklist(BLACKLIST_PATH)

    out: list[dict[str, Any]] = []
    for art in articles:
        d = _to_dict(art)
        source_name = d.get("source_name")
        src = registry.sources_by_name.get(source_name) if source_name else None
        if src and not d.get("source_url"):
            d["source_url"] = src.url

        # 美意識2: mainstream lookup
        d["美意識2_score"] = registry.score(source_name, d.get("url"))

        # 美意識4: blacklist penalty across title + description + body
        title = d.get("title", "") or ""
        body = _strip_html(d.get("body", ""))
        desc = _strip_html(d.get("description", ""))
        match_text = "\n".join(part for part in (title, desc, body) if part)
        penalty, hits = score_blacklist(match_text, blacklist)
        d["美意識4_penalty"] = penalty
        if hits:
            d["美意識4_hits"] = hits

        # Exclusion logic.
        excluded = False
        reason: str | None = None
        if penalty <= -10:
            excluded = True
            reason = (
                f"美意識4 累積ペナルティ {penalty}"
                f"（hits: {', '.join(hits[:3])}）"
            )
        else:
            # Universal podcast / audio-content filter (applies regardless of
            # region). Sprint 2 Step C: HBR IdeaCast 等の音声番組は紙面読書
            # 体験に整合しないため hard exclude する。
            pod_excluded, pod_reason = hard_filter.evaluate_podcast(
                url=d.get("url"), title=title, description=desc,
            )
            if pod_excluded:
                excluded = True
                reason = pod_reason
            else:
                # Universal description-length filter. Sprint 3 Step A
                # (2026-05-01): 日経のように description 空の RSS は紙面に
                # 「未完成の記事」を出してしまうため、< 30 字は弾く。
                desc_excluded, desc_reason = hard_filter.evaluate_description_length(d)
                if desc_excluded:
                    excluded = True
                    reason = desc_reason
                else:
                    region = src.category if src else None
                    hf_excluded, hf_reason = hard_filter.evaluate(
                        title, body or desc, region
                    )
                    if hf_excluded:
                        excluded = True
                        reason = hf_reason

        d["is_excluded"] = excluded
        d["exclusion_reason"] = reason
        out.append(d)
    return out
