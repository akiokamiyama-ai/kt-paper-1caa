#!/usr/bin/env python3
"""Regenerate Page I (front page) of the Tribune issue with live BBC News
content, translated to Japanese.

Refactored from ``experiment/regen_front_page.py`` to use the shared
modules: RssDriver for the BBC feed, BbcArticleScraper for body extraction,
translate.py for the Google→MyMemory pipeline, and render.py for HTML
output. Behavior is preserved: same article count, same explainer skip,
same AI-keyword promote, same surgical Page I replacement.
"""

from __future__ import annotations

import re
import sys
import time
from pathlib import Path

from .lib.config_loader import load_site_config
from .lib.drivers.html import BbcArticleScraper
from .lib.drivers.rss import RssDriver
from .lib.source import FetchMethod, Priority, Source, Status
from .render import build_page_one, replace_page_one
from .translate import translate, translate_meta

# --- pipeline knobs (preserved verbatim from the experiment script) ----

FEED_URL = "https://feeds.bbci.co.uk/news/business/rss.xml"
ARCHIVE = Path(__file__).resolve().parent.parent / "archive" / "2026-04-25.html"
N_ARTICLES = 4
TRANSLATE_DELAY = 0.3
FETCH_DELAY = 0.5
PROMOTE_KEYWORD = "AI"
SKIP_TITLE_PREFIXES = (
    "how ", "how does", "how do", "how can",
    "what ", "what is", "what are",
    "why ", "why is", "why do",
)
TOP_BODY_PARAGRAPHS = 4
SEC_BODY_PARAGRAPHS = 3


def _bbc_source() -> Source:
    """Construct a synthetic Source so the RssDriver can fetch the BBC feed."""
    return Source(
        name="BBC Business (regen pipeline)",
        url="https://www.bbc.com/business",
        category="business",
        priority=Priority.HIGH,
        status=Status.VERIFIED,
        fetch_method=FetchMethod.RSS,
        rss_url=FEED_URL,
    )


def _to_dict(article) -> dict:
    """Adapt an Article record to the dict shape the existing renderer expects."""
    return {
        "title": article.title,
        "link": article.link,
        "desc": article.description,
        "date": article.pub_date.isoformat() if article.pub_date else "",
    }


def filter_explainers(items: list[dict], n: int) -> list[dict]:
    kept: list[dict] = []
    for a in items:
        if any(a["title"].lower().startswith(p) for p in SKIP_TITLE_PREFIXES):
            print(f"  skip explainer: {a['title']}", file=sys.stderr)
            continue
        kept.append(a)
        if len(kept) >= n:
            break
    return kept


def promote(items: list[dict], keyword: str) -> list[dict]:
    pattern = re.compile(r"\b" + re.escape(keyword) + r"\b")
    for i, a in enumerate(items):
        if pattern.search(a["title"]):
            if i == 0:
                return items
            print(
                f"  promote to TOP (whole-word '{keyword}'): {a['title']}",
                file=sys.stderr,
            )
            return [items[i]] + items[:i] + items[i + 1 :]
    return items


def enrich_with_body(articles: list[dict], scraper: BbcArticleScraper) -> None:
    for i, a in enumerate(articles):
        max_n = TOP_BODY_PARAGRAPHS if i == 0 else SEC_BODY_PARAGRAPHS
        print(
            f"  [{i+1}] fetching {max_n} body paragraphs from source...",
            file=sys.stderr,
        )
        paragraphs = scraper.paragraphs(a["link"], max_n)
        time.sleep(FETCH_DELAY)
        translated: list[str] = []
        for j, p in enumerate(paragraphs):
            print(f"     translating ¶{j+1} ({len(p)} chars)", file=sys.stderr)
            t = translate(p)
            translated.append(t or p)
            time.sleep(TRANSLATE_DELAY)
        a["body_ja"] = translated


def main() -> int:
    site_cfg = load_site_config()
    rss = RssDriver(site_config=site_cfg)
    scraper = BbcArticleScraper()

    print(f"Fetching feed: {FEED_URL}", file=sys.stderr)
    bbc = _bbc_source()
    raw_articles = list(rss.fetch(bbc))
    raw = [_to_dict(a) for a in raw_articles]
    print(
        f"Parsed {len(raw)} items, filtering explainers, taking {N_ARTICLES}...",
        file=sys.stderr,
    )
    filtered = filter_explainers(raw, N_ARTICLES)
    if len(filtered) < N_ARTICLES:
        print(
            f"ERROR: need {N_ARTICLES}, got {len(filtered)} after filter",
            file=sys.stderr,
        )
        return 1
    promoted = promote(filtered, PROMOTE_KEYWORD)

    print("Translating titles and decks...", file=sys.stderr)
    translate_meta(promoted)

    print(
        "Fetching source articles and translating body paragraphs...",
        file=sys.stderr,
    )
    enrich_with_body(promoted, scraper)

    print("Building Page I block...", file=sys.stderr)
    page_html = build_page_one(promoted)

    print(f"Reading {ARCHIVE}", file=sys.stderr)
    original = ARCHIVE.read_text(encoding="utf-8")

    print("Replacing Page I section...", file=sys.stderr)
    updated = replace_page_one(original, page_html)

    if updated == original:
        print("ERROR: replacement produced no change", file=sys.stderr)
        return 1

    ARCHIVE.write_text(updated, encoding="utf-8")
    print(f"Wrote updated {ARCHIVE}", file=sys.stderr)
    print("", file=sys.stderr)
    print("=== Page I summary ===", file=sys.stderr)
    print(f"  TOP : {promoted[0]['title_ja']}", file=sys.stderr)
    print(
        f"        body paragraphs: {len(promoted[0].get('body_ja') or [])}",
        file=sys.stderr,
    )
    for i, s in enumerate(promoted[1:4], 1):
        print(f"  SEC{i}: {s['title_ja']}", file=sys.stderr)
        print(
            f"        body paragraphs: {len(s.get('body_ja') or [])}",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
