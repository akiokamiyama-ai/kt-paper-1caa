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
    """5/14 失敗パターン再現：早朝/夜の霧雨 (51) はあるが、日中 6-18 時は晴れ (1)。

    Sprint 6 fix 後は hourly[6:19] の最頻値を採用するため、code=1 が選ばれる。
    旧実装（daily.weather_code）なら 51 になっていた問題を解消。
    """
    payload = {
        "daily": {
            "time": ["2026-05-04"],
            "temperature_2m_max": [25.1],
            "temperature_2m_min": [15.2],
        },
        "hourly": {
            # 24 時間：00-05 時は霧雨 (51)、06-18 時は晴れ (1)、19-23 時は曇り (3)
            "weather_code": (
                [51] * 6   # 00:00-05:59
                + [1] * 13  # 06:00-18:59 ← daytime window
                + [3] * 5   # 19:00-23:59
            ),
        },
    }
    orig = _install_mock_urlopen(payload=payload)
    try:
        w = weather.fetch_weather(latitude=35.6895, longitude=139.6917)
    finally:
        _restore_urlopen(orig)
    _check("c1 fetch_weather OK → {min:15, max:25, code:1 (日中代表)}",
           w == {"min": 15, "max": 25, "code": 1}, f"got {w}")


def test_fetch_weather_rounds():
    """Floats like 25.7 are rounded to 26. weather_code は hourly から."""
    payload = {
        "daily": {
            "time": ["2026-05-04"],
            "temperature_2m_max": [25.7],
            "temperature_2m_min": [15.4],
        },
        "hourly": {
            "weather_code": [3] * 24,  # 終日 曇り
        },
    }
    orig = _install_mock_urlopen(payload=payload)
    try:
        w = weather.fetch_weather(latitude=35.6895, longitude=139.6917)
    finally:
        _restore_urlopen(orig)
    _check("c2 rounding: 25.7→26, 15.4→15, code=3",
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
    payload = {
        "daily": {"temperature_2m_max": [], "temperature_2m_min": []},
        "hourly": {"weather_code": []},
    }
    orig = _install_mock_urlopen(payload=payload)
    try:
        w = weather.fetch_weather(latitude=35.6895, longitude=139.6917)
    finally:
        _restore_urlopen(orig)
    _check("d3 empty arrays → None", w is None)


def test_fetch_weather_hourly_missing():
    """daily の温度はあるが hourly が空 → None で fallback（中途半端な表示を避ける）."""
    payload = {
        "daily": {
            "time": ["2026-05-14"],
            "temperature_2m_max": [24.0],
            "temperature_2m_min": [14.0],
        },
        "hourly": {"weather_code": []},
    }
    orig = _install_mock_urlopen(payload=payload)
    try:
        w = weather.fetch_weather(latitude=35.6895, longitude=139.6917)
    finally:
        _restore_urlopen(orig)
    _check("d4 hourly 欠落 → None（caller の fallback 経路へ）",
           w is None, f"got {w}")


# ---------------------------------------------------------------------------
# (f) 5/14 実データ回帰テスト：早朝の minor 霧雨に引っ張られない
# ---------------------------------------------------------------------------

def test_5_14_regression():
    """5/14 失敗パターンの再現：実観測 hourly で晴れ系が支配的なケース.

    実 API レスポンスから取った 24 時間分の値（[2,1,1,2,2,2,2,1,1,1,1,1,0,1,
    1,2,1,0,1,1,1,1,1,1]）で、daytime 6-18 時の最頻値が 1 (晴れ) となる
    ことを確認。旧 daily ロジックでは 51 (霧雨) を返していた問題が解消。
    """
    payload = {
        "daily": {
            "time": ["2026-05-14"],
            "temperature_2m_max": [23.3],
            "temperature_2m_min": [14.9],
        },
        "hourly": {
            "weather_code": [
                2, 1, 1, 2, 2, 2,    # 00-05 時
                2, 1, 1, 1, 1, 1, 0, 1, 1, 2, 1, 0, 1,  # 06-18 時 (13)
                1, 1, 1, 1, 1,        # 19-23 時
            ],
        },
    }
    orig = _install_mock_urlopen(payload=payload)
    try:
        w = weather.fetch_weather(latitude=35.6895, longitude=139.6917)
    finally:
        _restore_urlopen(orig)
    _check("f1 5/14 実データ：晴れ (1) が選ばれる（霧雨ではない）",
           w == {"min": 15, "max": 23, "code": 1}, f"got {w}")


def test_drizzle_dominant_daytime():
    """日中が霧雨支配なら、霧雨 (51) が選ばれる（過剰修正していないこと）."""
    payload = {
        "daily": {
            "time": ["2026-05-14"],
            "temperature_2m_max": [18.0],
            "temperature_2m_min": [12.0],
        },
        "hourly": {
            "weather_code": (
                [1] * 6      # 00-05 朝までは晴れ
                + [51] * 13  # 06-18 終日霧雨 ← daytime window
                + [1] * 5    # 19-23 夜は晴れ
            ),
        },
    }
    orig = _install_mock_urlopen(payload=payload)
    try:
        w = weather.fetch_weather(latitude=35.6895, longitude=139.6917)
    finally:
        _restore_urlopen(orig)
    _check("f2 日中霧雨支配 → 霧雨 (51) を正しく選ぶ",
           w == {"min": 12, "max": 18, "code": 51}, f"got {w}")


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
    test_fetch_weather_hourly_missing()
    print()
    print("(f) 5/14 回帰テスト & 日中支配の確認:")
    test_5_14_regression()
    test_drizzle_dominant_daytime()
    print()
    print("(e) Location constants:")
    test_location_constants()
    print()
    print(f"=== {PASS} passed, {FAIL} failed ===")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
