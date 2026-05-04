"""Unit tests for header.header_builder (Sprint 5 task #2, 2026-05-04).

Run::

    python3 -m tests.header.test_header_builder
"""

from __future__ import annotations

import sys
import tempfile
from datetime import date
from pathlib import Path

from scripts.header import header_builder, weather, markets, countdown

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


def _patch_weather(tokyo: dict | None, takao: dict | None):
    """Make weather.fetch_weather return tokyo/takao based on latitude."""
    original = weather.fetch_weather

    def fake(*, latitude, longitude, elevation=None, timeout=None):
        if abs(latitude - weather.TOKYO["latitude"]) < 0.01:
            return tokyo
        if abs(latitude - weather.TAKAOSAN["latitude"]) < 0.01:
            return takao
        return None
    weather.fetch_weather = fake
    return original


def _restore_weather(original):
    weather.fetch_weather = original


def _patch_markets(rows: list[dict]):
    """Replace fetch_all_markets to return a fixed list."""
    original = markets.fetch_all_markets
    markets.fetch_all_markets = lambda **kw: rows
    return original


def _restore_markets(original):
    markets.fetch_all_markets = original


def _patch_countdown(value: str | None):
    """Replace build_countdown_string to return a fixed string or None."""
    original = countdown.build_countdown_string
    countdown.build_countdown_string = lambda **kw: value
    return original


def _restore_countdown(original):
    countdown.build_countdown_string = original


# Re-bind the patched names back into header_builder's namespace too,
# since header_builder uses ``from . import countdown / weather / markets``.

# ---------------------------------------------------------------------------
# (a) Normal full render
# ---------------------------------------------------------------------------

def test_full_render_all_segments():
    ow = _patch_weather({"min": 15, "max": 25, "code": 51},
                        {"min": 12, "max": 28, "code": 51})
    om = _patch_markets([
        {"meta": {"label": "日経", "kind": "index", "css_class": "market-nikkei"},
         "fetched": {"close": 38420}, "diff_pct": 0.5},
        {"meta": {"label": "USD", "kind": "forex", "css_class": "forex-usd"},
         "fetched": {"close": 152.10}, "diff_pct": None},
    ])
    oc = _patch_countdown("フジロックまで 81日")
    try:
        html = header_builder.build_header_html(today=date(2026, 5, 4))
    finally:
        _restore_weather(ow)
        _restore_markets(om)
        _restore_countdown(oc)
    _check("a1 contains masthead-data wrapper",
           '<div class="masthead-data">' in html)
    _check("a2 contains row1 + row2",
           'class="masthead-data-row1"' in html
           and 'class="masthead-data-row2"' in html)
    _check("a3 Tokyo segment present",
           "東京 15-25℃ 霧雨" in html)
    _check("a4 高尾 segment present (elevation=599 effect not visible in test mock)",
           "高尾山 12-28℃ 霧雨" in html)
    _check("a5 countdown segment present", "フジロックまで 81日" in html)
    _check("a6 markets segment present",
           "日経 38,420 (+0.5%)" in html and "USD 152.10" in html)
    _check("a7 separators present",
           html.count('<span class="separator">／</span>') >= 3)


# ---------------------------------------------------------------------------
# (b) Weather failures degrade to '-' but row stays
# ---------------------------------------------------------------------------

def test_weather_partial_failure():
    ow = _patch_weather(None, {"min": 12, "max": 28, "code": 1})  # Tokyo failed
    om = _patch_markets([])
    oc = _patch_countdown("フジロックまで 81日")
    try:
        html = header_builder.build_header_html(today=date(2026, 5, 4))
    finally:
        _restore_weather(ow)
        _restore_markets(om)
        _restore_countdown(oc)
    _check("b1 Tokyo failed → '東京 -'",
           "東京 -" in html and "高尾山 12-28℃" in html,
           f"got tokyo_segment={'東京 -' in html}")


# ---------------------------------------------------------------------------
# (c) Countdown omitted on past/missing event
# ---------------------------------------------------------------------------

def test_countdown_none_omits_segment():
    ow = _patch_weather({"min": 15, "max": 25, "code": 0},
                        {"min": 12, "max": 22, "code": 0})
    om = _patch_markets([])
    oc = _patch_countdown(None)  # past or missing
    try:
        html = header_builder.build_header_html(today=date(2026, 5, 4))
    finally:
        _restore_weather(ow)
        _restore_markets(om)
        _restore_countdown(oc)
    _check("c1 countdown=None → no countdown span, no extra separator",
           "countdown" not in html
           and "まで" not in html)
    # Row 1 should still have weather
    _check("c2 row 1 still rendered without countdown",
           '<div class="masthead-data-row1">' in html)


# ---------------------------------------------------------------------------
# (d) All markets fail → row 2 omitted entirely
# ---------------------------------------------------------------------------

def test_all_markets_fail_omits_row2():
    ow = _patch_weather({"min": 15, "max": 25, "code": 0},
                        {"min": 12, "max": 22, "code": 0})
    # Every market entry has fetched=None
    om = _patch_markets([
        {"meta": {"label": "日経", "kind": "index", "css_class": "market-nikkei"},
         "fetched": None, "diff_pct": None},
        {"meta": {"label": "USD", "kind": "forex", "css_class": "forex-usd"},
         "fetched": None, "diff_pct": None},
    ])
    oc = _patch_countdown("フジロックまで 81日")
    try:
        html = header_builder.build_header_html(today=date(2026, 5, 4))
    finally:
        _restore_weather(ow)
        _restore_markets(om)
        _restore_countdown(oc)
    _check("d1 all markets fail → no row2",
           '<div class="masthead-data-row2">' not in html,
           f"row2 in html: {'row2' in html}")
    _check("d2 row1 still present",
           '<div class="masthead-data-row1">' in html)


# ---------------------------------------------------------------------------
# (e) Mixed: some markets succeed → row 2 present with mix
# ---------------------------------------------------------------------------

def test_partial_markets_renders_row2():
    ow = _patch_weather({"min": 15, "max": 25, "code": 0},
                        {"min": 12, "max": 22, "code": 0})
    om = _patch_markets([
        {"meta": {"label": "日経", "kind": "index", "css_class": "market-nikkei"},
         "fetched": {"close": 38420}, "diff_pct": 0.5},
        {"meta": {"label": "USD", "kind": "forex", "css_class": "forex-usd"},
         "fetched": None, "diff_pct": None},
    ])
    oc = _patch_countdown(None)
    try:
        html = header_builder.build_header_html(today=date(2026, 5, 4))
    finally:
        _restore_weather(ow)
        _restore_markets(om)
        _restore_countdown(oc)
    _check("e1 partial markets → row2 includes 日経 + USD -",
           '<div class="masthead-data-row2">' in html
           and "日経 38,420 (+0.5%)" in html
           and "USD -" in html)


def main() -> int:
    print("Header builder tests — Sprint 5 task #2")
    print()
    print("(a) Full render:")
    test_full_render_all_segments()
    print()
    print("(b) Weather partial failure:")
    test_weather_partial_failure()
    print()
    print("(c) Countdown omitted:")
    test_countdown_none_omits_segment()
    print()
    print("(d) All markets fail:")
    test_all_markets_fail_omits_row2()
    print()
    print("(e) Partial markets:")
    test_partial_markets_renders_row2()
    print()
    print(f"=== {PASS} passed, {FAIL} failed ===")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
