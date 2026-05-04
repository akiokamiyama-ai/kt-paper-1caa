"""Event countdown for the masthead-data row 1.

Sprint 5 task #2 (2026-05-04). Reads ``config/events.toml`` for a single
``[next_event]`` entry (name + ISO date). Past events return None so the
header builder omits the segment automatically.
"""

from __future__ import annotations

import sys
from datetime import date as _date_type
from pathlib import Path

# tomllib (Python 3.11+) — Tribune は Python 3.12 想定なので組み込み。
try:
    import tomllib
except ImportError:  # pragma: no cover — defensive for older Pythons
    import tomli as tomllib  # type: ignore

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_EVENTS_PATH = PROJECT_ROOT / "config" / "events.toml"


def load_next_event(*, path: Path | None = None) -> dict | None:
    """Return ``{"name": str, "date": "YYYY-MM-DD"}`` from ``[next_event]``.

    Returns ``None`` on missing file / parse error / missing keys.
    """
    p = path or DEFAULT_EVENTS_PATH
    if not p.exists():
        return None
    try:
        with open(p, "rb") as f:
            data = tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError) as e:
        print(f"  [countdown] events.toml parse failed: {type(e).__name__}", file=sys.stderr)
        return None
    next_event = data.get("next_event")
    if not isinstance(next_event, dict):
        return None
    name = next_event.get("name")
    date_str = next_event.get("date")
    if not (isinstance(name, str) and isinstance(date_str, str)):
        return None
    # Normalise tomllib-parsed date to ISO string. tomllib may return a
    # datetime.date already; coerce defensively.
    if hasattr(date_str, "isoformat"):
        date_str = date_str.isoformat()
    return {"name": name, "date": date_str}


def compute_days_until(target_date_str: str, *, today: _date_type | None = None) -> int | None:
    """Return integer days from ``today`` to ``target_date_str``.

    Returns ``None`` for past events (negative day count) or parse failure.
    """
    if today is None:
        today = _date_type.today()
    try:
        target = _date_type.fromisoformat(target_date_str)
    except (ValueError, TypeError):
        return None
    days = (target - today).days
    if days < 0:
        return None  # past event — caller omits the segment
    return days


def format_countdown(name: str, days: int) -> str:
    """Format ``"フジロックまで 81日"``."""
    return f"{name}まで {days}日"


def build_countdown_string(*, today: _date_type | None = None, path: Path | None = None) -> str | None:
    """End-to-end helper: load event + compute days + format.

    Returns the formatted string, or ``None`` if the segment should be
    omitted (no event configured / past event / parse failure).
    """
    event = load_next_event(path=path)
    if event is None:
        return None
    days = compute_days_until(event["date"], today=today)
    if days is None:
        return None
    return format_countdown(event["name"], days)
