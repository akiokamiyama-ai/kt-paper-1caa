"""Unit tests for header.weather (Sprint 5 task #2, 2026-05-04).

Tests use a urllib.request.urlopen monkey-patch so we don't hit the network.

Run::

    python3 -m tests.header.test_weather
"""

from __future__ import annotations

import io
import json
import sys
import urllib.error

from scripts.header import weather

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


# Mock urllib.request.urlopen
class _FakeResponse:
    def __init__(self, payload: dict):
        self._buf = io.BytesIO(json.dumps(payload).encode("utf-8"))

    def read(self):
        return self._buf.read()

    def __enter__(self):
        return self._buf

    def __exit__(self, *a):
        self._buf.close()


def _install_mock_urlopen(payload: dict | None = None, raise_exc=None):
    """Replace urlopen in the weather module's namespace."""
    original = weather.urllib.request.urlopen

    def fake(url, timeout=None):
        if raise_exc is not None:
            raise raise_exc
        return _FakeResponse(payload)
    weather.urllib.request.urlopen = fake
    return original


def _restore_urlopen(original):
    weather.urllib.request.urlopen = original


# ---------------------------------------------------------------------------
# (a) weather_code_label
# ---------------------------------------------------------------------------

def test_weather_code_label_known():
    _check("a1 code 0 → 快晴", weather.weather_code_label(0) == "快晴")
    _check("a2 code 51 → 霧雨", weather.weather_code_label(51) == "霧雨")
    _check("a3 code 95 → 雷雨", weather.weather_code_label(95) == "雷雨")


def test_weather_code_label_unknown():
    _check("a4 unknown code → '-'", weather.weather_code_label(999) == "-")
    _check("a5 None → '-'", weather.weather_code_label(None) == "-")


# ---------------------------------------------------------------------------
# (b) format_weather
# ---------------------------------------------------------------------------

def test_format_weather_normal():
    s = weather.format_weather({"min": 15, "max": 25, "code": 51})
    _check("b1 format normal → '15-25℃ 霧雨'", s == "15-25℃ 霧雨", f"got {s!r}")


def test_format_weather_clear():
    s = weather.format_weather({"min": 8, "max": 22, "code": 0})
    _check("b2 format clear → '8-22℃ 快晴'", s == "8-22℃ 快晴", f"got {s!r}")


def test_format_weather_none():
    _check("b3 format None → '-'", weather.format_weather(None) == "-")


# ---------------------------------------------------------------------------
# (c) fetch_weather success
# ---------------------------------------------------------------------------

def test_fetch_weather_success():
    payload = {
        "daily": {
            "time": ["2026-05-04"],
            "temperature_2m_max": [25.1],
            "temperature_2m_min": [15.2],
            "weather_code": [51],
        }
    }
    orig = _install_mock_urlopen(payload=payload)
    try:
        w = weather.fetch_weather(latitude=35.6895, longitude=139.6917)
    finally:
        _restore_urlopen(orig)
    _check("c1 fetch_weather OK → {min:15, max:25, code:51}",
           w == {"min": 15, "max": 25, "code": 51}, f"got {w}")


def test_fetch_weather_rounds():
    """Floats like 25.7 are rounded to 26."""
    payload = {
        "daily": {
            "time": ["2026-05-04"],
            "temperature_2m_max": [25.7],
            "temperature_2m_min": [15.4],
            "weather_code": [3],
        }
    }
    orig = _install_mock_urlopen(payload=payload)
    try:
        w = weather.fetch_weather(latitude=35.6895, longitude=139.6917)
    finally:
        _restore_urlopen(orig)
    _check("c2 rounding: 25.7→26, 15.4→15",
           w == {"min": 15, "max": 26, "code": 3}, f"got {w}")


# ---------------------------------------------------------------------------
# (d) fetch_weather failure modes
# ---------------------------------------------------------------------------

def test_fetch_weather_network_error():
    orig = _install_mock_urlopen(raise_exc=urllib.error.URLError("timeout"))
    try:
        w = weather.fetch_weather(latitude=35.6895, longitude=139.6917)
    finally:
        _restore_urlopen(orig)
    _check("d1 URLError → None", w is None)


def test_fetch_weather_missing_daily():
    payload = {"foo": "bar"}  # no daily
    orig = _install_mock_urlopen(payload=payload)
    try:
        w = weather.fetch_weather(latitude=35.6895, longitude=139.6917)
    finally:
        _restore_urlopen(orig)
    _check("d2 missing 'daily' → None", w is None)


def test_fetch_weather_empty_arrays():
    payload = {"daily": {"temperature_2m_max": [], "temperature_2m_min": [], "weather_code": []}}
    orig = _install_mock_urlopen(payload=payload)
    try:
        w = weather.fetch_weather(latitude=35.6895, longitude=139.6917)
    finally:
        _restore_urlopen(orig)
    _check("d3 empty arrays → None", w is None)


# ---------------------------------------------------------------------------
# (e) Constants sanity
# ---------------------------------------------------------------------------

def test_location_constants():
    _check("e1 TOKYO defined", weather.TOKYO["latitude"] == 35.6895)
    _check("e2 TAKAOSAN elevation=599",
           weather.TAKAOSAN["elevation"] == 599,
           f"got {weather.TAKAOSAN['elevation']}")


def main() -> int:
    print("Weather (Open-Meteo) tests — Sprint 5 task #2")
    print()
    print("(a) weather_code_label:")
    test_weather_code_label_known()
    test_weather_code_label_unknown()
    print()
    print("(b) format_weather:")
    test_format_weather_normal()
    test_format_weather_clear()
    test_format_weather_none()
    print()
    print("(c) fetch_weather success:")
    test_fetch_weather_success()
    test_fetch_weather_rounds()
    print()
    print("(d) fetch_weather failures:")
    test_fetch_weather_network_error()
    test_fetch_weather_missing_daily()
    test_fetch_weather_empty_arrays()
    print()
    print("(e) Location constants:")
    test_location_constants()
    print()
    print(f"=== {PASS} passed, {FAIL} failed ===")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
