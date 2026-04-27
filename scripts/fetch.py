#!/usr/bin/env python3
"""Fetch articles from sources/*.md sources.

The CLI dispatches each Source to a driver (RSS / HTML scraper), applies
URL deduplication against the last 7 days of fetch logs, and prints a
summary. By default it only touches ``Status.VERIFIED`` RSS sources; the
``--include-html`` flag also runs HTML-scrape stubs (which today emit a
single placeholder per source).

Examples
--------
    # All verified RSS sources, all categories, all priorities:
    python scripts/fetch.py

    # Only business sources, only High priority:
    python scripts/fetch.py --category business --priority high

    # Single named source (case-insensitive substring match):
    python scripts/fetch.py --source 'BBC Business'

    # Skip the dedupe filter (useful for first-run priming):
    python scripts/fetch.py --no-dedupe

    # Cap how many articles each source returns:
    python scripts/fetch.py --limit 5
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

from .lib.config_loader import load_site_config
from .lib.dedupe import append_today, dedupe
from .lib.drivers.html import HtmlScrapeDriver
from .lib.drivers.rss import RssDriver
from .lib.source import Article, FetchMethod, Priority, Source, load_all_sources

SOURCES_DIR = Path(__file__).resolve().parent.parent / "sources"


def select_sources(
    sources: list[Source],
    *,
    category: str | None,
    priority: str | None,
    name_substring: str | None,
    include_html: bool,
) -> list[Source]:
    out = []
    for s in sources:
        if not s.is_actionable:
            continue
        if s.fetch_method == FetchMethod.HTML and not include_html:
            continue
        if category and category.lower() not in s.category.lower():
            continue
        if priority and s.priority.value != priority.lower():
            continue
        if name_substring and name_substring.lower() not in s.name.lower():
            continue
        out.append(s)
    return out


def run(
    *,
    category: str | None = None,
    priority: str | None = None,
    name_substring: str | None = None,
    limit: int | None = None,
    no_dedupe: bool = False,
    include_html: bool = False,
    sources_dir: Path = SOURCES_DIR,
    write_log: bool = True,
) -> dict:
    """Programmatic entry point. Returns a summary dict for callers / tests."""
    site_cfg = load_site_config()
    rss = RssDriver(site_config=site_cfg)
    html = HtmlScrapeDriver(site_config=site_cfg)

    all_sources = load_all_sources(sources_dir)
    selected = select_sources(
        all_sources,
        category=category,
        priority=priority,
        name_substring=name_substring,
        include_html=include_html,
    )
    print(
        f"Selected {len(selected)} sources of {len(all_sources)} total "
        f"(category={category}, priority={priority}, "
        f"name~{name_substring}, include_html={include_html})",
        file=sys.stderr,
    )

    fetched: list[Article] = []
    by_source: Counter = Counter()
    failures: list[tuple[str, str]] = []
    for src in selected:
        driver = rss if src.fetch_method == FetchMethod.RSS else html
        try:
            arts = list(driver.fetch(src))
        except Exception as e:  # surface unexpected failures, keep going
            print(f"  [error] {src.name}: {e}", file=sys.stderr)
            failures.append((src.name, str(e)))
            continue
        if limit:
            arts = arts[:limit]
        by_source[src.name] = len(arts)
        fetched.extend(arts)

    pre_dedupe = len(fetched)
    if not no_dedupe:
        fetched = dedupe(fetched)
    post_dedupe = len(fetched)

    if write_log and not no_dedupe:
        append_today(fetched)

    summary = {
        "selected_sources": len(selected),
        "total_sources": len(all_sources),
        "articles_pre_dedupe": pre_dedupe,
        "articles_post_dedupe": post_dedupe,
        "by_source": dict(by_source),
        "failures": failures,
        "articles": fetched,
    }
    return summary


def _print_summary(summary: dict, show_articles: int = 0) -> None:
    print("", file=sys.stderr)
    print("=== Fetch summary ===", file=sys.stderr)
    print(
        f"  sources used:  {summary['selected_sources']} of "
        f"{summary['total_sources']}",
        file=sys.stderr,
    )
    print(f"  pre-dedupe:    {summary['articles_pre_dedupe']}", file=sys.stderr)
    print(f"  post-dedupe:   {summary['articles_post_dedupe']}", file=sys.stderr)
    if summary["failures"]:
        print(f"  failures:      {len(summary['failures'])}", file=sys.stderr)
        for name, err in summary["failures"][:5]:
            print(f"    - {name}: {err[:80]}", file=sys.stderr)
    print("", file=sys.stderr)
    print("  per-source counts:", file=sys.stderr)
    for name, n in sorted(summary["by_source"].items(), key=lambda kv: -kv[1])[:20]:
        print(f"    {n:4d}  {name}", file=sys.stderr)
    if show_articles:
        print("", file=sys.stderr)
        print(f"  first {show_articles} articles after dedupe:", file=sys.stderr)
        for a in summary["articles"][:show_articles]:
            date_s = a.pub_date.strftime("%Y-%m-%d") if a.pub_date else "????-??-??"
            print(f"    [{date_s}] [{a.source_name}] {a.title[:80]}", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="fetch", description="Fetch Tribune source articles"
    )
    p.add_argument("--category", help="filter by category substring (e.g. business)")
    p.add_argument(
        "--priority",
        choices=["high", "medium", "reference"],
        help="filter by priority bucket",
    )
    p.add_argument("--source", help="filter by source name substring")
    p.add_argument("--limit", type=int, help="cap articles per source")
    p.add_argument(
        "--no-dedupe",
        action="store_true",
        help="skip URL-based dedupe and skip writing today's log",
    )
    p.add_argument(
        "--include-html",
        action="store_true",
        help="also run HTML-scrape sources (placeholder driver today)",
    )
    p.add_argument(
        "--show",
        type=int,
        default=10,
        help="how many post-dedupe articles to print",
    )
    args = p.parse_args(argv)

    summary = run(
        category=args.category,
        priority=args.priority,
        name_substring=args.source,
        limit=args.limit,
        no_dedupe=args.no_dedupe,
        include_html=args.include_html,
    )
    _print_summary(summary, show_articles=args.show)
    return 0 if summary["articles_post_dedupe"] > 0 or args.no_dedupe else 1


if __name__ == "__main__":
    sys.exit(main())
