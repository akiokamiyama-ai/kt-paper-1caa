"""One-shot bootstrap: parse archive HTML for past days, write displayed_urls logs.

Sprint 2 Step D: pre-populate ``logs/displayed_urls_2026-04-29.json`` and
``logs/displayed_urls_2026-04-30.json`` so that 5/1 onwards have a
recency window to dedup against.

Run::

    python3 -m scripts.bootstrap_displayed_urls
    python3 -m scripts.bootstrap_displayed_urls --date 2026-04-29  # single date
    python3 -m scripts.bootstrap_displayed_urls --dry-run          # don't write

Extraction patterns (mirrors ``regen_front_page_v2.build_page_one_v2`` /
``build_page_two_v2`` output):

* Page I: ``<a href="...">`` inside ``<p class="byline" ...>原題：…全文：``
  is the source URL. There are 4 such links per Page I (TOP + SEC1〜3).
* Page II: each ``<div class="briefing-row">`` block contains
  ``<h4 class="headline-m"><a href="...">`` for the selected article.
  ``<div class="company">{社名}…`` identifies which company.
  「本日休載」rows have no ``<h4><a>`` link → URL is None.
"""

from __future__ import annotations

import argparse
import html as html_module
import re
import sys
from datetime import date
from pathlib import Path

from .selector.dedup_filter import write_displayed_urls_log

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ARCHIVE_DIR = PROJECT_ROOT / "archive"

DEFAULT_DATES = ("2026-04-29", "2026-04-30")

# Map display-name (as it appears in <div class="company">) to company_key.
DISPLAY_TO_KEY: dict[str, str] = {
    "Cocolomi":     "cocolomi",
    "Human Energy": "human_energy",
    "Web-Repo":     "web_repo",
}


def _extract_section(html: str, page_class: str) -> str | None:
    """Extract a <section class='page page-X'>...</section> block."""
    marker = f'<section class="page {page_class}">'
    if marker not in html:
        return None
    start = html.find(marker)
    end = html.find("</section>", start)
    if end < 0:
        return None
    return html[start : end + len("</section>")]


def extract_page1_urls(archive_html: str) -> list[str]:
    """Extract the 4 article URLs from Page I (TOP + SEC1〜3, in order)."""
    section = _extract_section(archive_html, "page-one")
    if section is None:
        return []
    # Page I bylines wrap `<a href="...">` immediately after "全文：" — pull
    # those links specifically, otherwise we'd also capture the masthead /
    # font preconnect anchors elsewhere in <head>. The byline pattern is:
    #   <p class="byline" ...>原題：<em>…</em>　全文：<a href="…" target="_blank" rel="…">…</a></p>
    pattern = re.compile(
        r'class="byline"[^>]*>[^<]*原題[^<]*<em>[^<]*</em>[^<]*全文[^<]*'
        r'<a href="(https?://[^"]+)"',
        re.DOTALL,
    )
    seen: set[str] = set()
    urls: list[str] = []
    for m in pattern.finditer(section):
        # Archive HTML has URLs HTML-escaped (e.g., "&" → "&amp;"). Decode
        # so the recorded URL matches the in-memory candidate URL.
        url = html_module.unescape(m.group(1))
        if url not in seen:
            seen.add(url)
            urls.append(url)
    return urls


def extract_page2_urls(archive_html: str) -> dict[str, str | None]:
    """Extract per-company URL from Page II briefing-rows.

    Returns a dict keyed by company_key with the URL string (or None for
    "本日休載" rows).
    """
    section = _extract_section(archive_html, "page-two")
    if section is None:
        return {k: None for k in DISPLAY_TO_KEY.values()}
    # Split into briefing-row chunks. The first split fragment is the
    # preamble before the first <div class="briefing-row">.
    chunks = re.split(r'<div class="briefing-row"', section)[1:]
    result: dict[str, str | None] = {k: None for k in DISPLAY_TO_KEY.values()}
    for chunk in chunks:
        company_key = _identify_company(chunk)
        if not company_key:
            continue
        url_match = re.search(
            r'<h4 class="headline-m">\s*<a href="(https?://[^"]+)"',
            chunk,
        )
        if url_match:
            result[company_key] = html_module.unescape(url_match.group(1))
        # else: no <h4><a> means 本日休載 row → None (already initialised).
    return result


def _identify_company(chunk: str) -> str | None:
    """Find the company display name in a briefing-row chunk."""
    # Pattern: <div class="company">\n        <display_name>\n        <span class="jp">…
    m = re.search(
        r'<div class="company">\s*([^\n<]+?)\s*<span class="jp">',
        chunk,
        re.DOTALL,
    )
    if not m:
        return None
    display = m.group(1).strip()
    return DISPLAY_TO_KEY.get(display)


def bootstrap_one(target_date: date, *, write: bool = True) -> dict:
    """Read archive/<date>.html, extract Page I+II URLs, optionally write log."""
    archive_path = ARCHIVE_DIR / f"{target_date.isoformat()}.html"
    if not archive_path.exists():
        return {
            "date": target_date.isoformat(),
            "status": "missing",
            "archive_path": str(archive_path),
        }
    html = archive_path.read_text(encoding="utf-8")
    page1_urls = extract_page1_urls(html)
    page2_urls = extract_page2_urls(html)
    summary = {
        "date": target_date.isoformat(),
        "archive_path": str(archive_path),
        "page1_urls": page1_urls,
        "page2_urls": page2_urls,
        "page1_count": len(page1_urls),
        "page2_count": sum(1 for v in page2_urls.values() if v),
    }
    if write:
        path = write_displayed_urls_log(
            target_date, page1_urls=page1_urls, page2_urls_by_company=page2_urls,
        )
        summary["log_path"] = str(path)
        summary["status"] = "written"
    else:
        summary["status"] = "dry_run"
    return summary


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="bootstrap_displayed_urls",
        description="Pre-populate logs/displayed_urls_*.json from past archive HTML",
    )
    p.add_argument(
        "--date",
        action="append",
        help=(
            "ISO date (YYYY-MM-DD); repeat for multiple dates. "
            f"Defaults to {DEFAULT_DATES}"
        ),
    )
    p.add_argument("--dry-run", action="store_true", help="parse but don't write logs")
    args = p.parse_args(argv)

    targets: list[date] = []
    raw = args.date or DEFAULT_DATES
    for s in raw:
        try:
            targets.append(date.fromisoformat(s))
        except ValueError:
            print(f"invalid --date {s!r}", file=sys.stderr)
            return 1

    print()
    print("=== Bootstrap displayed-URL logs ===")
    print()
    for d in targets:
        s = bootstrap_one(d, write=not args.dry_run)
        print(f"  [{s['date']}] {s['status']}")
        if s["status"] == "missing":
            print(f"      archive not found: {s['archive_path']}")
            continue
        print(f"      Page I:  {s['page1_count']} urls")
        for url in s["page1_urls"]:
            print(f"        - {url[:90]}")
        print(f"      Page II: {s['page2_count']} urls (out of 3 companies)")
        for company_key, url in s["page2_urls"].items():
            display = {"cocolomi": "Cocolomi", "human_energy": "Human Energy", "web_repo": "Web-Repo"}.get(company_key, company_key)
            if url:
                print(f"        - {display:<14}: {url[:80]}")
            else:
                print(f"        - {display:<14}: (本日休載)")
        if "log_path" in s:
            print(f"      written to: {s['log_path']}")
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
