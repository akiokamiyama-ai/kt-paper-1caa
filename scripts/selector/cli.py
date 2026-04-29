"""Smoke-test CLI for Stage 1.

    python3 -m scripts.selector.cli --source 'BBC Business' --limit 5

Fetches via the existing fetch.py runner (no dedupe write, no log
mutation) and prints the four Stage 1 fields per article. The CLI is a
debugging aid; it does not write to archive/, logs/, or the live front
page.
"""

from __future__ import annotations

import argparse
import json
import sys

from ..fetch import run as fetch_run
from .stage1 import run_stage1


def _format_text(scored: list[dict]) -> str:
    lines = ["", "=== Stage 1 results ==="]
    excluded_n = sum(1 for a in scored if a["is_excluded"])
    lines.append(f"  total: {len(scored)}  (excluded: {excluded_n})")
    for i, a in enumerate(scored, 1):
        lines.append("")
        title = (a.get("title") or "")[:80]
        lines.append(f"  [{i}] {title}")
        lines.append(f"      url:               {a.get('url')}")
        lines.append(f"      source_name:       {a.get('source_name')}")
        lines.append(f"      source_url:        {a.get('source_url')}")
        lines.append(f"      美意識2_score:     {a['美意識2_score']}")
        lines.append(f"      美意識4_penalty:   {a['美意識4_penalty']}")
        if a.get("美意識4_hits"):
            lines.append(f"      美意識4_hits:      {a['美意識4_hits']}")
        lines.append(f"      is_excluded:       {a['is_excluded']}")
        lines.append(f"      exclusion_reason:  {a.get('exclusion_reason')}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="selector", description="Stage 1 mechanical filters smoke test"
    )
    p.add_argument(
        "--source",
        default="BBC Business",
        help="source name substring (default: 'BBC Business')",
    )
    p.add_argument(
        "--category",
        help="category substring filter (e.g. business, books)",
    )
    p.add_argument(
        "--priority",
        choices=["high", "medium", "reference"],
        help="priority bucket filter",
    )
    p.add_argument("--limit", type=int, default=5, help="articles per source")
    p.add_argument(
        "--json",
        action="store_true",
        help="emit full JSON of scored articles instead of summary",
    )
    args = p.parse_args(argv)

    summary = fetch_run(
        category=args.category,
        priority=args.priority,
        name_substring=args.source,
        limit=args.limit,
        no_dedupe=True,
        write_log=False,
    )
    articles = summary["articles"]
    if not articles:
        print("No articles fetched.", file=sys.stderr)
        return 1

    scored = run_stage1(articles)

    if args.json:
        clean = [{k: v for k, v in a.items() if k != "raw"} for a in scored]
        print(json.dumps(clean, ensure_ascii=False, indent=2, default=str))
    else:
        print(_format_text(scored))
    return 0


if __name__ == "__main__":
    sys.exit(main())
