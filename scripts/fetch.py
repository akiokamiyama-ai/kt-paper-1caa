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
from datetime import date
from collections import Counter
from pathlib import Path

from .lib.config_loader import load_site_config
from .lib.dedupe import append_today, dedupe
from .lib.drivers.fitness_business import (
    HOST as FITNESS_BUSINESS_HOST,
    FitnessBusinessDriver,
)
from .lib.drivers.html import HtmlScrapeDriver
from .lib.drivers.jfa import HOST as JFA_HOST, JfaDriver
from .lib.drivers.jftc import HOST as JFTC_HOST, JftcDriver
from .lib.drivers.ppc import HOST as PPC_HOST, PpcDriver
from .lib.drivers.que_shincho import HOST as QUE_HOST, QueShinchoDriver
from .lib.drivers.rss import RssDriver
from .lib.jst import jst_today
from .lib.source import Article, FetchMethod, Priority, Source, load_all_sources

SOURCES_DIR = Path(__file__).resolve().parent.parent / "sources"

# C163 (Sprint 13, 2026-08-14): 到達不能ソース（BLOCKED_RUNNER_IP）の週次プローブ。
#
# 経産省 / JFTC / ダ・ヴィンチWeb / ナタリー音楽 の 4 件は、フィード自体は生きて
# いる（ローカルからは 200 OK）が GHA runner の IP からは 403/405 が返る。毎朝
# 叩いても必ず失敗し、ログに 6-10 件のノイズを出して**新規の障害を見えにくく
# していた**（8/14 の Reuters 503 が埋もれた）。
#
# 日次 fetch からは外すが、「静かに諦める」と復旧を見落とす（C156 の教訓：
# BbcArticleScraper が silently 0 件を返し続けて 10 日以上気づかれなかった）。
# そこで **週 1 回だけプローブ**して、復旧していれば気づけるようにする。
#
# 月曜を選んだ理由は特にない（曜日が固定でさえあれば良い）。JST 基準。
UNREACHABLE_PROBE_WEEKDAY = 0  # 0=月曜


def is_probe_day(today: date | None = None) -> bool:
    """C163: 到達不能ソースをプローブする日か（週 1 回、JST 基準）。"""
    return (today or jst_today()).weekday() == UNREACHABLE_PROBE_WEEKDAY


def select_sources(
    sources: list[Source],
    *,
    category: str | None,
    priority: str | None,
    name_substring: str | None,
    include_html: bool,
    probe_unreachable: bool | None = None,
) -> list[Source]:
    """条件に合うソースを選ぶ。

    C163: ``is_unreachable``（BLOCKED_RUNNER_IP marker 付き）のソースは
    日次 fetch から除外する。``probe_unreachable`` が True の日（既定では
    週 1 回のプローブ日）だけ含めて、復旧していないかを確認する。
    """
    if probe_unreachable is None:
        probe_unreachable = is_probe_day()
    out = []
    for s in sources:
        if not s.is_actionable:
            continue
        if s.is_unreachable and not probe_unreachable:
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
    # C42 案A (Sprint 9, 2026-06-04): 新潮QUE (FORESIGHT 後継) は RSS 不在の
    # ため sitemap → /node/{id}/ HTML 経路で個別 scrape。fetch_method=HTML の
    # source に対して host が que.dailyshincho.jp なら QueShinchoDriver を
    # 優先する（dispatch ループ内で分岐）。
    que_shincho = QueShinchoDriver(site_config=site_cfg)
    # C120 (Sprint 11, 2026-07-04): 公取委 (JFTC) 報道発表は RSS 未提供の
    # ため、月別 index → 個別記事の 2 段 fetch で scrape。host が
    # www.jftc.go.jp なら JftcDriver を使う。
    jftc = JftcDriver(site_config=site_cfg)
    # C122 (Sprint 11, 2026-07-04): Fitness Business (Web-Repo フィットネス
    # 事業ドメイン) は RSS 未提供のため sitemap.xml + 個別記事 JSON-LD
    # 経由で scrape。host が business.fitnessclub.jp なら FitnessBusinessDriver
    # を使う。
    fitness_business = FitnessBusinessDriver(site_config=site_cfg)
    # C127 (Sprint 11, 2026-07-09): JFA (日本フランチャイズチェーン協会) は
    # RSS 未提供のためプレスリリース一覧ページから <dt>日付</dt><dd><h2><a>
    # タイトル</a></h2></dd> の DL ペアを抽出。host が www.jfa-fc.or.jp なら
    # JfaDriver を使う。
    jfa = JfaDriver(site_config=site_cfg)
    # C142 (Sprint 12, 2026-07-13): PPC (個人情報保護委員会) は RSS 未提供の
    # ため報道発表一覧ページから <time datetime>+<div class="news-text"><a>
    # を抽出。host が www.ppc.go.jp なら PpcDriver を使う。JFA と同型の
    # 1 HTTP fetch / list-only 設計。
    ppc = PpcDriver(site_config=site_cfg)

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
    probed_ok: list[str] = []
    for src in selected:
        if src.fetch_method == FetchMethod.RSS:
            driver = rss
        elif QUE_HOST in (src.url or ""):
            driver = que_shincho
        elif JFTC_HOST in (src.url or ""):
            driver = jftc
        elif FITNESS_BUSINESS_HOST in (src.url or ""):
            driver = fitness_business
        elif JFA_HOST in (src.url or ""):
            driver = jfa
        elif PPC_HOST in (src.url or ""):
            driver = ppc
        else:
            driver = html
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
        # C163: 到達不能マークのソースが取れたら復旧の可能性。目立たせる。
        if src.is_unreachable and arts:
            probed_ok.append(src.name)
            print(
                f"  [C163] 到達不能マークの {src.name} が {len(arts)} 件取得できました。"
                "復旧した可能性があります。sources/*.md の fetch_status を見直してください。",
                file=sys.stderr,
            )

    # C163: プローブ日に到達不能ソースが依然ダメだったことも記録する
    # （「静かに諦める」を避ける。C156 の教訓）。
    probed = [x.name for x in selected if x.is_unreachable]
    if probed:
        still_blocked = [n for n in probed if n not in probed_ok]
        print(
            f"  [C163] 週次プローブ: {len(probed)} 件中 復旧 {len(probed_ok)} / "
            f"依然ブロック {len(still_blocked)}"
            + (f" → {', '.join(still_blocked)}" if still_blocked else ""),
            file=sys.stderr,
        )

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
