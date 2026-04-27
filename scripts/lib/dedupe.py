"""URL deduplication via per-day JSON logs.

The ``logs/urls_YYYY-MM-DD.json`` files record every article URL the fetch
pipeline emitted on a given day. On the next run, :func:`dedupe` filters
out any article whose URL appears in the last :data:`RETENTION_DAYS` files.

Format of one log file::

    {
      "date": "2026-04-27",
      "urls": ["https://...", ...],
      "by_source": {
        "Source Name": ["https://...", ...]
      }
    }
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

from .source import Article

LOG_DIR = Path(__file__).resolve().parent.parent.parent / "logs"
RETENTION_DAYS = 7


def _log_path(d: date) -> Path:
    return LOG_DIR / f"urls_{d.isoformat()}.json"


def load_recent_urls(today: date | None = None) -> set[str]:
    """Read the last RETENTION_DAYS log files and return the union of URLs."""
    base = today or date.today()
    out: set[str] = set()
    for offset in range(RETENTION_DAYS):
        d = base - timedelta(days=offset)
        path = _log_path(d)
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        out.update(data.get("urls") or [])
    return out


def append_today(articles: list[Article], today: date | None = None) -> Path:
    """Write today's articles to ``logs/urls_<today>.json``.

    If a log already exists for today (e.g. multiple fetch runs in one day),
    URLs are merged so a re-run doesn't drop earlier entries.
    """
    base = today or date.today()
    path = _log_path(base)
    existing_urls: list[str] = []
    existing_by_src: dict[str, list[str]] = {}
    if path.exists():
        try:
            prev = json.loads(path.read_text(encoding="utf-8"))
            existing_urls = list(prev.get("urls") or [])
            existing_by_src = dict(prev.get("by_source") or {})
        except json.JSONDecodeError:
            pass
    seen: set[str] = set(existing_urls)
    by_src: dict[str, list[str]] = {k: list(v) for k, v in existing_by_src.items()}
    for art in articles:
        fp = art.fingerprint
        if not fp or fp in seen:
            continue
        seen.add(fp)
        by_src.setdefault(art.source_name, []).append(fp)
    payload = {
        "date": base.isoformat(),
        "urls": sorted(seen),
        "by_source": {k: sorted(v) for k, v in by_src.items()},
    }
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return path


def dedupe(articles: list[Article], today: date | None = None) -> list[Article]:
    """Drop articles whose URL was already emitted in the last 7 days.

    The current day's log is included in the lookup so a re-run within the
    same day doesn't duplicate articles either.
    """
    seen = load_recent_urls(today)
    out: list[Article] = []
    for art in articles:
        if art.fingerprint in seen:
            continue
        out.append(art)
    return out
