"""Per-day displayed-URL log + recency dedup filter.

Sprint 2 Step D 実装。同じ記事が複数日にわたって朝刊に表示されるのを
防ぐためのレイヤー。``logs/displayed_urls_YYYY-MM-DD.json`` に **その日に
実際に紙面で表示した URL** を記録し、翌朝以降の選定時に過去 N 日ぶんを
集めて除外する。

ルール（``docs/`` の設計議論で確定）：

* **第1面**：N=7 日（過去1週間）に表示された URL は除外
* **第2面**：N=3 日、社別（Cocolomi/Human Energy/Web-Repo それぞれ独立）
* **第3面**：N=7 日（page3_design_v1.md §6.1）
* **第4面**：N=30 日（学術記事は更新頻度低、長めのウィンドウ）
* **第5面**：N=30 日、書籍/音楽/アウトドアの URL（料理は URL なし）
* **第6面**：N=30 日、セレンディピティ記事1本（page6_url、null 可）

判定基準は「表示された記事」のみ。Stage 2 で評価したが選定されなかった
記事は対象外（翌日以降に選定される可能性を残す）。

Log file shape (``logs/displayed_urls_YYYY-MM-DD.json``):

    {
      "date": "2026-04-30",
      "page1_urls": ["url1", "url2", "url3", "url4"],
      "page2_urls": {
        "cocolomi": "url",
        "human_energy": "url",
        "web_repo": null
      },
      "page3_urls": ["urlR1", "urlR2", null, "urlR4", "urlR5", "urlR6"],
      "page4_urls": ["urlA", "urlB", "urlC"],
      "page5_urls": {"books": "urlB", "music": "urlM", "outdoor": "urlO"},
      "page6_url": "urlSerendipity"
    }

``page3_urls`` は領域順（R1〜R6）の固定長6リスト。「本日該当なし」の
領域は ``null`` で埋める。Sprint 2 までの旧形式ログ（page3_urls 不在）は
空リストとして扱う（後方互換）。

``page4_urls`` は第4面の学術記事3本（順序保持）。3日ローテーションの
ため、1日ごとに同じ3本が記録される（rotation 切替時に新たな3本に
変わる）。Sprint 3 Step B 以前の旧形式ログ（page4_urls 不在）も
空リスト扱い。

``page5_urls`` は第5面の3カラム（books / music / outdoor）のそれぞれの
URL を領域別に持つ dict。料理カラムは URL なしのため含めない（cooking_history.json で別管理）。
``None`` を渡すと空 dict で書き込み（Sprint 3 Step C 以前の後方互換）。

``page6_url`` は第6面のセレンディピティ記事 URL（単一）。記事候補ゼロで
placeholder 表示の日は ``null``。``None`` を渡すと ``null`` で書き込み
（Sprint 3 Step D 以前の後方互換）。

Public API:

* ``load_displayed_urls_log(target_date)``        → dict | None
* ``write_displayed_urls_log(target_date, page1_urls, page2_urls_by_company,
  page3_urls=None, page4_urls=None, page5_urls=None, page6_url=None)``
* ``load_recently_displayed_urls(days_back, page, company_key=None, until_date=None)``
* ``filter_recently_displayed(articles, displayed_urls)``
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Literal

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
LOG_DIR = PROJECT_ROOT / "logs"


def _log_path(target_date: date) -> Path:
    return LOG_DIR / f"displayed_urls_{target_date.isoformat()}.json"


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------

def load_displayed_urls_log(target_date: date) -> dict | None:
    """Load ``logs/displayed_urls_YYYY-MM-DD.json``. Return None if missing."""
    path = _log_path(target_date)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        # Corrupt log — treat as missing rather than crash the pipeline.
        return None


def load_recently_displayed_urls(
    days_back: int,
    page: Literal["page1", "page2", "page3", "page4", "page5"],
    company_key: str | None = None,
    until_date: date | None = None,
) -> set[str]:
    """Walk the previous ``days_back`` days' displayed-URL logs.

    The window is ``[until_date - days_back, until_date - 1]`` inclusive —
    the target date itself is **not** included (we don't dedup against
    today's own selection).

    Parameters
    ----------
    days_back :
        Number of days to look back. Page I uses 7, Page II uses 3, Page III
        uses 7, Page IV uses 30, Page V uses 30.
    page :
        ``"page1"`` collects every URL from the day's ``page1_urls`` list.
        ``"page2"`` requires ``company_key`` and collects only that
        company's selected URL (if any).
        ``"page3"`` collects every non-null URL from the day's
        ``page3_urls`` list (固定長6、null は placeholder の slot)。
        ``"page4"`` collects every URL from the day's ``page4_urls`` list
        (3 本 × ローテーション期間)。
        ``"page5"`` collects every URL from the day's ``page5_urls`` dict
        across all areas (books / music / outdoor). Cooking has no URL.
    company_key :
        For ``page="page2"``, one of ``"cocolomi"`` / ``"human_energy"`` /
        ``"web_repo"``. Ignored for page1 / page3 / page4 / page5.
    until_date :
        Defaults to today. Pass an explicit date to simulate a future run
        (e.g., ``--date 2026-05-01`` dry-run).
    """
    if days_back < 1:
        return set()
    if until_date is None:
        until_date = date.today()
    if page == "page2" and not company_key:
        raise ValueError("company_key is required when page='page2'")

    urls: set[str] = set()
    for i in range(1, days_back + 1):
        d = until_date - timedelta(days=i)
        log = load_displayed_urls_log(d)
        if log is None:
            continue
        if page == "page1":
            for u in log.get("page1_urls", []) or []:
                if u:
                    urls.add(u)
        elif page == "page2":
            company_url = (log.get("page2_urls", {}) or {}).get(company_key)
            if company_url:
                urls.add(company_url)
        elif page == "page3":
            for u in log.get("page3_urls", []) or []:
                if u:
                    urls.add(u)
        elif page == "page4":
            for u in log.get("page4_urls", []) or []:
                if u:
                    urls.add(u)
        elif page == "page5":
            for u in (log.get("page5_urls", {}) or {}).values():
                if u:
                    urls.add(u)
        else:
            raise ValueError(f"unknown page {page!r}")
    return urls


# ---------------------------------------------------------------------------
# Filter
# ---------------------------------------------------------------------------

def filter_recently_displayed(
    articles: list[dict],
    displayed_urls: set[str],
) -> list[dict]:
    """Return articles whose ``url`` field is **not** in ``displayed_urls``.

    Order is preserved. Articles missing a ``url`` field are kept (we
    cannot dedup what we cannot identify).
    """
    if not displayed_urls:
        return list(articles)
    return [a for a in articles if a.get("url") not in displayed_urls]


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------

def write_displayed_urls_log(
    target_date: date,
    page1_urls: list[str],
    page2_urls_by_company: dict[str, str | None],
    page3_urls: list[str | None] | None = None,
    page4_urls: list[str] | None = None,
    page5_urls: dict[str, str | None] | None = None,
    page6_url: str | None = None,
) -> Path:
    """Write the day's displayed URLs to ``logs/displayed_urls_<date>.json``.

    Replaces any existing log for the same date — re-runs (e.g., dry-run
    followed by production) overwrite, since the production output is the
    canonical record of what was actually shown.

    ``page3_urls`` は領域順（R1〜R6）の長さ6リスト。「本日該当なし」の
    slot は ``None``。``None`` を渡すと空リストで書き込み（page3 未実装の
    Sprint 2 までの後方互換）。

    ``page4_urls`` は学術記事3本のリスト（順序保持）。``None`` を渡すと
    空リストで書き込み（Sprint 3 Step B 以前の後方互換）。

    ``page5_urls`` は領域別 dict ``{"books": url|None, "music": url|None,
    "outdoor": url|None}``。料理カラムは URL なしのため含めない。
    ``None`` を渡すと空 dict で書き込み（Sprint 3 Step C 以前の後方互換）。

    ``page6_url`` はセレンディピティ記事 URL の単一文字列または ``None``。
    """
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    # Deduplicate while preserving order (Page I rarely has duplicates but
    # be defensive).
    seen: set[str] = set()
    unique_page1: list[str] = []
    for u in page1_urls:
        if u and u not in seen:
            seen.add(u)
            unique_page1.append(u)
    data = {
        "date": target_date.isoformat(),
        "page1_urls": unique_page1,
        "page2_urls": {k: (v if v else None) for k, v in page2_urls_by_company.items()},
        "page3_urls": list(page3_urls) if page3_urls is not None else [],
        "page4_urls": list(page4_urls) if page4_urls is not None else [],
        "page5_urls": (
            {k: (v if v else None) for k, v in page5_urls.items()}
            if page5_urls is not None else {}
        ),
        "page6_url": page6_url if page6_url else None,
    }
    path = _log_path(target_date)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
