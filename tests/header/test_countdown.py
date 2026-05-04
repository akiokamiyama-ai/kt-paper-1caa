"""Unit tests for header.countdown (Sprint 5 task #2, 2026-05-04).

Run::

    python3 -m tests.header.test_countdown
"""

from __future__ import annotations

import sys
import tempfile
from datetime import date
from pathlib import Path

from scripts.header import countdown

PASS = 0
FAIL = 0


def _check(label: str, condition: bool, detail: str = "") -> bool:
    global PASS, FAIL
    sym = "✓" if condition else "✗"
    line = f"  {sym} {label}"
    if detail:
        line += f"  ({detail})"
    print(line)
    if condition:
        PASS += 1
    else:
        FAIL += 1
    return condition


def _write_toml(path: Path, content: str):
    path.write_text(content, encoding="utf-8")


# ---------------------------------------------------------------------------
# (a) load_next_event
# ---------------------------------------------------------------------------

def test_load_next_event_success():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "events.toml"
        _write_toml(path, '[next_event]\nname = "フジロック"\ndate = "2026-07-24"\n')
        ev = countdown.load_next_event(path=path)
    _check("a1 valid TOML → {name, date}",
           ev == {"name": "フジロック", "date": "2026-07-24"},
           f"got {ev}")


def test_load_next_event_missing_file():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "no_such.toml"
        ev = countdown.load_next_event(path=path)
    _check("a2 missing file → None", ev is None)


def test_load_next_event_invalid_toml():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "bad.toml"
        _write_toml(path, "this is not valid toml { [")
        ev = countdown.load_next_event(path=path)
    _check("a3 invalid TOML → None", ev is None)


def test_load_next_event_missing_keys():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "incomplete.toml"
        _write_toml(path, '[next_event]\nname = "X"\n')  # no date
        ev = countdown.load_next_event(path=path)
    _check("a4 missing date key → None", ev is None)


# ---------------------------------------------------------------------------
# (b) compute_days_until
# ---------------------------------------------------------------------------

def test_compute_days_future():
    days = countdown.compute_days_until("2026-07-24", today=date(2026, 5, 4))
    _check("b1 5/4 → 7/24 = 81 days", days == 81, f"got {days}")


def test_compute_days_past_returns_none():
    days = countdown.compute_days_until("2026-04-01", today=date(2026, 5, 4))
    _check("b2 past event → None", days is None, f"got {days}")


def test_compute_days_today_returns_zero():
    days = countdown.compute_days_until("2026-05-04", today=date(2026, 5, 4))
    _check("b3 same day → 0", days == 0, f"got {days}")


def test_compute_days_invalid_date():
    days = countdown.compute_days_until("not-a-date", today=date(2026, 5, 4))
    _check("b4 invalid date string → None", days is None)


# ---------------------------------------------------------------------------
# (c) format_countdown + build_countdown_string
# ---------------------------------------------------------------------------

def test_format_countdown_string():
    s = countdown.format_countdown("フジロック", 81)
    _check("c1 'フジロックまで 81日'",
           s == "フジロックまで 81日", f"got {s!r}")


def test_build_countdown_full_path():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "events.toml"
        _write_toml(path, '[next_event]\nname = "サマソニ"\ndate = "2026-08-15"\n')
        s = countdown.build_countdown_string(today=date(2026, 5, 4), path=path)
    _check("c2 build full string from TOML + today",
           s == "サマソニまで 103日", f"got {s!r}")


def test_build_countdown_past_returns_none():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "events.toml"
        _write_toml(path, '[next_event]\nname = "Past"\ndate = "2026-04-01"\n')
        s = countdown.build_countdown_string(today=date(2026, 5, 4), path=path)
    _check("c3 past event → None (segment omitted)", s is None)


def main() -> int:
    print("Countdown (events.toml) tests — Sprint 5 task #2")
    print()
    print("(a) load_next_event:")
    test_load_next_event_success()
    test_load_next_event_missing_file()
    test_load_next_event_invalid_toml()
    test_load_next_event_missing_keys()
    print()
    print("(b) compute_days_until:")
    test_compute_days_future()
    test_compute_days_past_returns_none()
    test_compute_days_today_returns_zero()
    test_compute_days_invalid_date()
    print()
    print("(c) format / build:")
    test_format_countdown_string()
    test_build_countdown_full_path()
    test_build_countdown_past_returns_none()
    print()
    print(f"=== {PASS} passed, {FAIL} failed ===")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
