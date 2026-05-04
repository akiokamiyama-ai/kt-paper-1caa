"""Unit tests for header.markets (Sprint 5 task #2, 2026-05-04).

Run::

    python3 -m tests.header.test_markets
"""

from __future__ import annotations

import io
import json
import sys
import tempfile
import urllib.error
from pathlib import Path

from scripts.header import markets

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


# ---------------------------------------------------------------------------
# (a) _parse_csv_line
# ---------------------------------------------------------------------------

def test_parse_csv_line_normal():
    text = (
        "Symbol,Date,Time,Open,High,Low,Close,Volume\n"
        "^NKX,2026-05-01,08:45:03,59379.12,59706.7,59263.5,59513.12,2015819000\n"
    )
    parsed = markets._parse_csv_line("^nkx", text)
    _check("a1 parse normal CSV",
           parsed == {"symbol": "^NKX", "date": "2026-05-01", "close": 59513.12})


def test_parse_csv_line_no_data_row():
    text = "Symbol,Date,Time,Open,High,Low,Close,Volume\n"
    _check("a2 only header → None",
           markets._parse_csv_line("^nkx", text) is None)


def test_parse_csv_line_n_d_close():
    text = (
        "Symbol,Date,Time,Open,High,Low,Close,Volume\n"
        "^NKX,2026-05-01,08:45:03,N/D,N/D,N/D,N/D,N/D\n"
    )
    _check("a3 N/D close → None",
           markets._parse_csv_line("^nkx", text) is None)


# ---------------------------------------------------------------------------
# (b) fetch_market_close
# ---------------------------------------------------------------------------

class _FakeResponse:
    def __init__(self, text: str):
        self._buf = io.BytesIO(text.encode("utf-8"))

    def read(self):
        return self._buf.read()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self._buf.close()


def _install_mock_urlopen(text: str | None = None, raise_exc=None):
    original = markets.urllib.request.urlopen

    def fake(req, timeout=None):
        if raise_exc is not None:
            raise raise_exc
        return _FakeResponse(text or "")
    markets.urllib.request.urlopen = fake
    return original


def _restore_urlopen(original):
    markets.urllib.request.urlopen = original


def test_fetch_market_close_success():
    text = (
        "Symbol,Date,Time,Open,High,Low,Close,Volume\n"
        "^NKX,2026-05-01,08:45:03,59379.12,59706.7,59263.5,59513.12,2015819000\n"
    )
    orig = _install_mock_urlopen(text=text)
    try:
        r = markets.fetch_market_close("^nkx")
    finally:
        _restore_urlopen(orig)
    _check("b1 fetch_market_close success",
           r == {"symbol": "^NKX", "date": "2026-05-01", "close": 59513.12})


def test_fetch_market_close_network_error():
    orig = _install_mock_urlopen(raise_exc=urllib.error.URLError("timeout"))
    try:
        r = markets.fetch_market_close("^nkx")
    finally:
        _restore_urlopen(orig)
    _check("b2 URLError → None", r is None)


# ---------------------------------------------------------------------------
# (c) History I/O
# ---------------------------------------------------------------------------

def test_history_load_missing_returns_empty():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "missing.json"
        h = markets.load_history(path=path)
    _check("c1 missing file → empty dict", h == {})


def test_history_load_corrupt_returns_empty():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "corrupt.json"
        path.write_text("not valid json")
        h = markets.load_history(path=path)
    _check("c2 corrupt file → empty dict", h == {})


def test_history_append_new_entry():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "h.json"
        markets.append_history_entry(
            "^nkx", date="2026-05-01", close=59513.12, history_path=path,
        )
        h = markets.load_history(path=path)
    _check("c3 append new entry",
           h.get("^nkx") == [{"date": "2026-05-01", "close": 59513.12}])


def test_history_append_duplicate_skipped():
    """Same-date append → existing value kept (first-write wins)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "h.json"
        markets.append_history_entry(
            "^nkx", date="2026-05-01", close=59000.0, history_path=path,
        )
        markets.append_history_entry(
            "^nkx", date="2026-05-01", close=99999.0, history_path=path,
        )
        h = markets.load_history(path=path)
    _check("c4 duplicate date skipped (existing kept)",
           h.get("^nkx") == [{"date": "2026-05-01", "close": 59000.0}])


def test_history_prune_to_keep_days():
    """When entries exceed keep_days, oldest are dropped."""
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "h.json"
        # Add 5 entries with keep_days=3
        for i, day in enumerate(["2026-04-01", "2026-04-02", "2026-04-03", "2026-04-04", "2026-04-05"]):
            markets.append_history_entry(
                "^nkx", date=day, close=100.0 + i, history_path=path, keep_days=3,
            )
        h = markets.load_history(path=path)
    entries = h.get("^nkx", [])
    dates = [e["date"] for e in entries]
    _check("c5 keep_days=3 retains last 3",
           len(entries) == 3 and dates == ["2026-04-03", "2026-04-04", "2026-04-05"],
           f"got {dates}")


# ---------------------------------------------------------------------------
# (d) compute_diff_pct
# ---------------------------------------------------------------------------

def test_diff_no_history_returns_none():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "h.json"
        diff = markets.compute_diff_pct(
            "^nkx", current_date="2026-05-01", current_close=100.0,
            history_path=path,
        )
    _check("d1 no history → None", diff is None)


def test_diff_with_prior_entry():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "h.json"
        markets.append_history_entry(
            "^nkx", date="2026-04-30", close=100.0, history_path=path,
        )
        diff = markets.compute_diff_pct(
            "^nkx", current_date="2026-05-01", current_close=101.0,
            history_path=path,
        )
    _check("d2 100→101 → +1%", abs((diff or 0) - 1.0) < 0.01,
           f"got {diff}")


def test_diff_negative():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "h.json"
        markets.append_history_entry(
            "^dji", date="2026-04-30", close=200.0, history_path=path,
        )
        diff = markets.compute_diff_pct(
            "^dji", current_date="2026-05-01", current_close=198.0,
            history_path=path,
        )
    _check("d3 200→198 → -1%", abs((diff or 0) - (-1.0)) < 0.01)


def test_diff_only_same_date_returns_none():
    """If only the current_date exists in history (no prior), return None."""
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "h.json"
        markets.append_history_entry(
            "^nkx", date="2026-05-01", close=100.0, history_path=path,
        )
        diff = markets.compute_diff_pct(
            "^nkx", current_date="2026-05-01", current_close=101.0,
            history_path=path,
        )
    _check("d4 only same-date in history → None", diff is None)


# ---------------------------------------------------------------------------
# (e) format_market_value
# ---------------------------------------------------------------------------

def test_format_index_with_diff():
    meta = {"label": "日経", "kind": "index"}
    out = markets.format_market_value(meta, {"close": 38420}, 0.5)
    _check("e1 index +0.5% → '日経 38,420 (+0.5%)'",
           out == "日経 38,420 (+0.5%)", f"got {out!r}")


def test_format_index_negative_diff():
    meta = {"label": "NYダウ", "kind": "index"}
    out = markets.format_market_value(meta, {"close": 38950}, -0.3)
    _check("e2 index -0.3% → 'NYダウ 38,950 (-0.3%)'",
           out == "NYダウ 38,950 (-0.3%)", f"got {out!r}")


def test_format_index_no_diff():
    meta = {"label": "S&P 500", "kind": "index"}
    out = markets.format_market_value(meta, {"close": 5200}, None)
    _check("e3 index no diff → 'S&P 500 5,200 (-)'",
           out == "S&P 500 5,200 (-)", f"got {out!r}")


def test_format_forex():
    meta = {"label": "USD", "kind": "forex"}
    out = markets.format_market_value(meta, {"close": 152.10}, None)
    _check("e4 forex → 'USD 152.10'",
           out == "USD 152.10", f"got {out!r}")


def test_format_no_data():
    meta = {"label": "日経", "kind": "index"}
    out = markets.format_market_value(meta, None, None)
    _check("e5 no fetched → '日経 -'", out == "日経 -", f"got {out!r}")


def main() -> int:
    print("Markets (Stooq) tests — Sprint 5 task #2")
    print()
    print("(a) _parse_csv_line:")
    test_parse_csv_line_normal()
    test_parse_csv_line_no_data_row()
    test_parse_csv_line_n_d_close()
    print()
    print("(b) fetch_market_close:")
    test_fetch_market_close_success()
    test_fetch_market_close_network_error()
    print()
    print("(c) History I/O:")
    test_history_load_missing_returns_empty()
    test_history_load_corrupt_returns_empty()
    test_history_append_new_entry()
    test_history_append_duplicate_skipped()
    test_history_prune_to_keep_days()
    print()
    print("(d) compute_diff_pct:")
    test_diff_no_history_returns_none()
    test_diff_with_prior_entry()
    test_diff_negative()
    test_diff_only_same_date_returns_none()
    print()
    print("(e) format_market_value:")
    test_format_index_with_diff()
    test_format_index_negative_diff()
    test_format_index_no_diff()
    test_format_forex()
    test_format_no_data()
    print()
    print(f"=== {PASS} passed, {FAIL} failed ===")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
