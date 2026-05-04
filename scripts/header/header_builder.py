"""Compose the 2-row masthead-data block (weather + countdown / markets).

Sprint 5 task #2 (2026-05-04). Independently fetches each subsystem so
that any single failure degrades that segment to ``-`` without dropping
the whole row. If all market fetches fail, the second row is omitted
entirely.
"""

from __future__ import annotations

import html
from datetime import date as _date_type
from pathlib import Path

from . import countdown as _countdown
from . import markets as _markets
from . import weather as _weather


def _esc(s: str) -> str:
    return html.escape(s or "")


def _row1_segments(today: _date_type | None = None) -> list[tuple[str, str]]:
    """Return (css_class, text) tuples for row 1 (weather + countdown)."""
    out: list[tuple[str, str]] = []

    # Tokyo
    tokyo_w = _weather.fetch_weather(
        latitude=_weather.TOKYO["latitude"],
        longitude=_weather.TOKYO["longitude"],
        elevation=_weather.TOKYO["elevation"],
    )
    out.append(("weather-tokyo",
                f"{_weather.TOKYO['label']} {_weather.format_weather(tokyo_w)}"))

    # 高尾山
    takao_w = _weather.fetch_weather(
        latitude=_weather.TAKAOSAN["latitude"],
        longitude=_weather.TAKAOSAN["longitude"],
        elevation=_weather.TAKAOSAN["elevation"],
    )
    out.append(("weather-takao",
                f"{_weather.TAKAOSAN['label']} {_weather.format_weather(takao_w)}"))

    # Countdown — omit segment entirely if missing/past
    countdown_str = _countdown.build_countdown_string(today=today)
    if countdown_str is not None:
        out.append(("countdown", countdown_str))

    return out


def _row2_segments(history_path: Path | None = None) -> list[tuple[str, str]] | None:
    """Return (css_class, text) tuples for row 2 (markets).

    Returns ``None`` if **all** market fetches failed — caller omits row 2.
    """
    rows = _markets.fetch_all_markets(history_path=history_path)
    out: list[tuple[str, str]] = []
    success_count = 0
    for r in rows:
        meta = r["meta"]
        text = _markets.format_market_value(meta, r["fetched"], r["diff_pct"])
        out.append((meta["css_class"], text))
        if r["fetched"] is not None:
            success_count += 1
    if success_count == 0:
        return None
    return out


def _render_row(css_class: str, segments: list[tuple[str, str]]) -> str:
    """Render one row with ／-separated spans. Empty segments → no row."""
    if not segments:
        return ""
    parts: list[str] = []
    for i, (span_class, text) in enumerate(segments):
        if i > 0:
            parts.append('<span class="separator">／</span>')
        parts.append(f'<span class="{_esc(span_class)}">{_esc(text)}</span>')
    return f'    <div class="{css_class}">\n      ' + "\n      ".join(parts) + "\n    </div>"


def build_header_html(
    *,
    today: _date_type | None = None,
    history_path: Path | None = None,
) -> str:
    """Build the ``<div class="masthead-data">`` block.

    Returns ``""`` if both rows are empty (all fetches failed).
    """
    row1 = _row1_segments(today=today)
    row2 = _row2_segments(history_path=history_path)

    row1_html = _render_row("masthead-data-row1", row1) if row1 else ""
    row2_html = _render_row("masthead-data-row2", row2) if row2 else ""

    if not row1_html and not row2_html:
        return ""
    inner = "\n".join(p for p in (row1_html, row2_html) if p)
    return f'<div class="masthead-data">\n{inner}\n  </div>\n  '
