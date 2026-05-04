"""Open-Meteo weather client for the masthead-data row 1.

Sprint 5 task #2 (2026-05-04). Fetches today's max/min temperature + WMO
weather code for two locations:
  - Tokyo (35.6895, 139.6917, auto elevation ~40m)
  - 高尾山頂 (35.6256, 139.2433, elevation=599 explicit)

Open-Meteo の気象モデル解像度は 0.05° (~5km) のため、緯度経度の小さな
差は同一グリッドにスナップされる。実質的に効くのは ``elevation`` パラメータの
みで、lapse rate (~0.6℃/100m) で標高補正される。神山さん（ハイカー）の
体感に合わせて高尾山は山頂標高を明示する。

外部 API 失敗時は ``None`` を返し、caller (header_builder) は fallback
表示を選択する。
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request

OPEN_METEO_BASE = "https://api.open-meteo.com/v1/forecast"
TIMEOUT_SEC = 3


# WMO Weather Interpretation Codes → 日本語簡潔表現。新聞風の硬さを優先、
# 未知コードは "-" にフォールバックして masthead を破壊しない。
WEATHER_CODE_JA: dict[int, str] = {
    0: "快晴",
    1: "晴れ",
    2: "晴れ時々曇り",
    3: "曇り",
    45: "霧",
    48: "霧氷",
    51: "霧雨",
    53: "霧雨",
    55: "強い霧雨",
    56: "凍る霧雨",
    57: "凍る霧雨",
    61: "小雨",
    63: "雨",
    65: "強い雨",
    66: "凍雨",
    67: "凍雨",
    71: "小雪",
    73: "雪",
    75: "大雪",
    77: "霧雪",
    80: "にわか雨",
    81: "にわか雨",
    82: "強いにわか雨",
    85: "にわか雪",
    86: "強いにわか雪",
    95: "雷雨",
    96: "雷雨と雹",
    99: "強い雷雨と雹",
}


# Tokyo / 高尾山頂 の固定座標。表示メタデータも一緒に保持する。
TOKYO = {
    "label": "東京",
    "latitude": 35.6895,
    "longitude": 139.6917,
    "elevation": None,  # auto
}
TAKAOSAN = {
    "label": "高尾山",
    "latitude": 35.6256,
    "longitude": 139.2433,
    "elevation": 599,  # 山頂標高を明示してハイカー体感に寄せる
}


def fetch_weather(
    *,
    latitude: float,
    longitude: float,
    elevation: int | None = None,
    timeout: int = TIMEOUT_SEC,
) -> dict | None:
    """Fetch today's daily weather from Open-Meteo.

    Returns
    -------
    dict | None
        ``{"min": int, "max": int, "code": int}`` on success, ``None`` on
        any failure (network / timeout / parse / missing fields).
    """
    params = (
        f"latitude={latitude}&longitude={longitude}"
        "&daily=temperature_2m_max,temperature_2m_min,weather_code"
        "&timezone=Asia/Tokyo&forecast_days=1"
    )
    if elevation is not None:
        params += f"&elevation={elevation}"
    url = f"{OPEN_METEO_BASE}?{params}"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            data = json.load(resp)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
        print(f"  [weather] FAIL {latitude},{longitude}: {type(e).__name__}", file=sys.stderr)
        return None
    daily = data.get("daily") or {}
    try:
        max_arr = daily.get("temperature_2m_max") or []
        min_arr = daily.get("temperature_2m_min") or []
        code_arr = daily.get("weather_code") or []
        if not (max_arr and min_arr and code_arr):
            return None
        return {
            "min": round(min_arr[0]),
            "max": round(max_arr[0]),
            "code": int(code_arr[0]),
        }
    except (TypeError, ValueError, IndexError) as e:
        print(f"  [weather] parse error: {e}", file=sys.stderr)
        return None


def weather_code_label(code: int | None) -> str:
    """WMO code を日本語ラベルに。未知コードは ``"-"``。"""
    if code is None:
        return "-"
    return WEATHER_CODE_JA.get(code, "-")


def format_weather(weather: dict | None) -> str:
    """Format the per-location masthead string, e.g. ``"15-25℃ 霧雨"``.

    Returns ``"-"`` if ``weather`` is None (caller handles missing).
    """
    if not weather:
        return "-"
    label = weather_code_label(weather.get("code"))
    return f"{weather['min']}-{weather['max']}℃ {label}"
