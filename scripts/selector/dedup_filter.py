"""Per-day displayed-URL log + recency dedup filter.

Sprint 2 Step D 実装。同じ記事が複数日にわたって朝刊に表示されるのを
防ぐためのレイヤー。``logs/displayed_urls_YYYY-MM-DD.json`` に **その日に
実際に紙面で表示した URL** を記録し、翌朝以降の選定時に過去 N 日ぶんを
集めて除外する。

ルール（``docs/`` の設計議論で確定）：

* **第1面**：N=7 日（過去1週間）に表示された URL は除外
* **第2面**：N=3 日、社別（Cocolomi/Human Energy/Web-Repo それぞれ独立）

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
      }
    }

Public API:

* ``load_displayed_urls_log(target_date)``        → dict | None
* ``write_displayed_urls_log(target_date, page1_urls, page2_urls_by_company)``
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
    page: Literal["page1", "page2"],
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
        Number of days to look back. Page I uses 7, Page II uses 3.
    page :
        ``"page1"`` collects every URL from the day's ``page1_urls`` list.
        ``"page2"`` requires ``company_key`` and collects only that
        company's selected URL (if any).
    company_key :
        For ``page="page2"``, one of ``"cocolomi"`` / ``"human_energy"`` /
        ``"web_repo"``. Ignored for page1.
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
) -> Path:
    """Write the day's displayed URLs to ``logs/displayed_urls_<date>.json``.

    Replaces any existing log for the same date — re-runs (e.g., dry-run
    followed by production) overwrite, since the production output is the
    canonical record of what was actually shown.
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
    }
    path = _log_path(target_date)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
