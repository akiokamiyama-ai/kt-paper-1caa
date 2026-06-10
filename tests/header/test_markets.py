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
# (a) _parse_yahoo_chart — C66 (2026-06-08): Yahoo Finance v8 chart JSON parser
# ---------------------------------------------------------------------------

def _yahoo_payload(
    timestamps: list[int],
    closes: list[float | None],
    *,
    gmt_offset: int = 0,
    regular_market_price: float | None = None,
    regular_market_time: int | None = None,
) -> str:
    meta: dict = {"gmtoffset": gmt_offset}
    if regular_market_price is not None:
        meta["regularMarketPrice"] = regular_market_price
    if regular_market_time is not None:
        meta["regularMarketTime"] = regular_market_time
    return json.dumps({
        "chart": {
            "result": [{
                "meta": meta,
                "timestamp": timestamps,
                "indicators": {"quote": [{"close": closes}]},
            }],
            "error": None,
        }
    })


def test_parse_yahoo_chart_normal():
    # 2026-05-01 09:00 UTC = 18:00 JST ish, doesn't matter for daily granularity
    payload = _yahoo_payload(
        timestamps=[1777593600, 1777680000, 1777766400],  # 5/01, 5/02, 5/03 UTC
        closes=[59500.0, 59513.12, 59600.0],
    )
    parsed = markets._parse_yahoo_chart("^nkx", payload)
    _check(
        "a1 parse Yahoo JSON: last close + last timestamp date",
        parsed is not None
        and parsed["symbol"] == "^nkx"
        and parsed["close"] == 59600.0
        and parsed["date"] == "2026-05-03",
        f"got {parsed}",
    )


def test_parse_yahoo_chart_trailing_null_skipped():
    """末尾 null は skip して、その手前の non-null close を採用."""
    payload = _yahoo_payload(
        timestamps=[1777593600, 1777680000, 1777766400],
        closes=[59500.0, 59513.12, None],
    )
    parsed = markets._parse_yahoo_chart("^nkx", payload)
    _check(
        "a2 trailing null → 1 つ前の non-null close を採用",
        parsed == {"symbol": "^nkx", "date": "2026-05-02", "close": 59513.12},
        f"got {parsed}",
    )


def test_parse_yahoo_chart_all_null():
    payload = _yahoo_payload(
        timestamps=[1777593600, 1777680000],
        closes=[None, None],
    )
    _check(
        "a3 全 null close → None",
        markets._parse_yahoo_chart("^nkx", payload) is None,
    )


def test_parse_yahoo_chart_error_field():
    """Yahoo が error フィールドを返した場合は None."""
    payload = json.dumps({
        "chart": {
            "result": None,
            "error": {"code": "Not Found", "description": "No data found"},
        }
    })
    _check(
        "a4 yahoo error フィールド → None",
        markets._parse_yahoo_chart("^nkx", payload) is None,
    )


def test_parse_yahoo_chart_empty_result():
    payload = json.dumps({"chart": {"result": [], "error": None}})
    _check(
        "a5 result=[] → None",
        markets._parse_yahoo_chart("^nkx", payload) is None,
    )


def test_parse_yahoo_chart_malformed_json():
    _check(
        "a6 malformed JSON → None",
        markets._parse_yahoo_chart("^nkx", "{not json") is None,
    )


def test_yahoo_symbol_mapping():
    """SYMBOLS 全 5 件に yahoo_symbol が設定され、_yahoo_symbol_for で解決."""
    expected = {
        "^nkx": "^N225", "^dji": "^DJI", "^spx": "^GSPC",
        "usdjpy": "JPY=X", "eurjpy": "EURJPY=X",
    }
    all_ok = True
    for k, v in expected.items():
        got = markets._yahoo_symbol_for(k)
        if got != v:
            all_ok = False
            _check(f"a7 {k} → {v}", False, f"got {got}")
    _check("a7 全 5 symbol が yahoo_symbol にマップされる", all_ok)
    _check(
        "a8 未知 symbol → None",
        markets._yahoo_symbol_for("xyz") is None,
    )


# ---------------------------------------------------------------------------
# (a-c68) C68 (2026-06-09): regularMarketPrice fallback + exchange-local date
# ---------------------------------------------------------------------------

def test_parse_yahoo_uses_exchange_local_date():
    """JST 取引所 (gmtoffset=32400) では bar ts のローカル日付を採用."""
    # ts=1777593600 = 2026-05-01 00:00 UTC = 2026-05-01 09:00 JST
    # local date = 2026-05-01 (両 tz で同じ偶然)
    payload = _yahoo_payload(
        timestamps=[1777593600], closes=[100.0], gmt_offset=32400,
    )
    parsed = markets._parse_yahoo_chart("^nkx", payload)
    _check(
        "a9 JST exchange の bar date は exchange-local で解釈",
        parsed["date"] == "2026-05-01",
        f"got {parsed}",
    )


def test_parse_yahoo_rmp_fallback_when_latest_bar_is_null():
    """C68 真因対策：最新 bar.close=None でも regularMarketPrice があれば採用.

    Nikkei の 6/8 月曜引け値が daily bar に未反映で None、meta.regularMarketPrice
    に 64024.6 が入っている、という実 Yahoo 状態を再現。
    """
    # JST 取引所 (^N225 と同じ)
    # ts=1780617600 = 2026-06-05 09:00 JST (=金曜の bar、close 入り)
    # ts=1780876800 = 2026-06-08 09:00 JST (=月曜の bar、close=None)
    # rmt=1780901103 = 2026-06-08 15:45 JST (=月曜引け時刻)
    payload = _yahoo_payload(
        timestamps=[1780617600, 1780876800],
        closes=[66588.12, None],
        gmt_offset=32400,
        regular_market_price=64024.6,
        regular_market_time=1780901103,
    )
    parsed = markets._parse_yahoo_chart("^nkx", payload)
    _check(
        "a10 最新 bar=null + rmp 新しい → rmp を採用",
        parsed is not None
        and parsed["close"] == 64024.6
        and parsed["date"] == "2026-06-08",
        f"got {parsed}",
    )


def test_parse_yahoo_rmp_ignored_when_older_than_latest_bar():
    """rmp の date が bar より古い場合は bar を優先（rmp は補助）."""
    # bar.date=2026-05-03、rmp date=2026-05-02 → bar を採用
    payload = _yahoo_payload(
        timestamps=[1777593600, 1777680000, 1777766400],
        closes=[100.0, 101.0, 102.0],
        gmt_offset=0,
        regular_market_price=99.0,
        regular_market_time=1777680000,  # 2026-05-02
    )
    parsed = markets._parse_yahoo_chart("xyz", payload)
    _check(
        "a11 rmp が bar より古い → bar を採用",
        parsed["close"] == 102.0 and parsed["date"] == "2026-05-03",
        f"got {parsed}",
    )


def test_parse_yahoo_rmp_used_when_bar_all_null():
    """全 bar が null だが rmp はある → rmp を採用（fallback）."""
    payload = _yahoo_payload(
        timestamps=[1777593600, 1777680000],
        closes=[None, None],
        gmt_offset=0,
        regular_market_price=99.0,
        regular_market_time=1777680000,
    )
    parsed = markets._parse_yahoo_chart("xyz", payload)
    _check(
        "a12 全 bar=null でも rmp で値が出る",
        parsed is not None and parsed["close"] == 99.0,
        f"got {parsed}",
    )


def test_parse_yahoo_no_rmp_no_bar_returns_none():
    """rmp も bar も無効 → None."""
    payload = _yahoo_payload(
        timestamps=[1777593600], closes=[None], gmt_offset=0,
    )
    _check(
        "a13 rmp も bar も無効 → None",
        markets._parse_yahoo_chart("xyz", payload) is None,
    )


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
    # C66: Yahoo Finance v8 chart JSON 形式
    # C68 第二弾 (2026-06-10): all_bars キーが同梱される
    payload = _yahoo_payload(
        timestamps=[1777593600],  # 2026-05-01 (UTC)
        closes=[59513.12],
    )
    orig = _install_mock_urlopen(text=payload)
    try:
        r = markets.fetch_market_close("^nkx")
    finally:
        _restore_urlopen(orig)
    _check(
        "b1 fetch_market_close success: symbol/date/close",
        r is not None
        and r["symbol"] == "^nkx"
        and r["date"] == "2026-05-01"
        and r["close"] == 59513.12,
        f"got {r}",
    )
    _check(
        "b1b fetch_market_close 戻り値に all_bars が含まれる (C68 第二弾)",
        r is not None and "all_bars" in r and r["all_bars"] == [
            {"symbol": "^nkx", "date": "2026-05-01", "close": 59513.12},
        ],
        f"got all_bars={r.get('all_bars') if r else None!r}",
    )


def test_fetch_market_close_network_error():
    orig = _install_mock_urlopen(raise_exc=urllib.error.URLError("timeout"))
    try:
        r = markets.fetch_market_close("^nkx")
    finally:
        _restore_urlopen(orig)
    _check("b2 URLError → None", r is None)


def test_fetch_market_close_unknown_symbol():
    """設定外 symbol → fetch せず None."""
    _check(
        "b3 unknown symbol → None (early return)",
        markets.fetch_market_close("nonexistent") is None,
    )


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


def test_format_forex_no_diff():
    """Sprint 7 (2026-05-19): 履歴なし時は (-) を付ける（C6）."""
    meta = {"label": "USD", "kind": "forex"}
    out = markets.format_market_value(meta, {"close": 152.10}, None)
    _check("e4 forex no diff → 'USD 152.10 (-)'",
           out == "USD 152.10 (-)", f"got {out!r}")


def test_format_forex_with_positive_diff():
    """Sprint 8 (2026-05-20): C15 — 為替前日比は ％ ではなく円表示。

    diff_pct=0.3 から前日 close を逆算し差分を円で表示：
    prior = 158.86 / 1.003 ≒ 158.3809、diff_yen ≒ +0.48 円。
    """
    meta = {"label": "USD", "kind": "forex"}
    out = markets.format_market_value(meta, {"close": 158.86}, 0.3)
    _check("e5 forex +0.3% → 'USD 158.86 (+0.48円)'（円表示）",
           out == "USD 158.86 (+0.48円)", f"got {out!r}")


def test_format_forex_with_negative_diff():
    """diff_pct=-0.7 → prior = 185.11 / 0.993 ≒ 186.4149、diff_yen ≒ -1.30 円。"""
    meta = {"label": "EUR", "kind": "forex"}
    out = markets.format_market_value(meta, {"close": 185.11}, -0.7)
    _check("e6 forex -0.7% → 'EUR 185.11 (-1.30円)'（円表示）",
           out == "EUR 185.11 (-1.30円)", f"got {out!r}")


def test_format_no_data():
    meta = {"label": "日経", "kind": "index"}
    out = markets.format_market_value(meta, None, None)
    _check("e7 no fetched → '日経 -'", out == "日経 -", f"got {out!r}")


# ---------------------------------------------------------------------------
# (f) C68 第二弾 (2026-06-10): _parse_yahoo_chart_all_bars + fetch_all_markets
#     の history backfill 挙動
# ---------------------------------------------------------------------------

def test_all_bars_returns_non_null_in_date_order():
    payload = _yahoo_payload(
        timestamps=[1780617600, 1780876800, 1780963200],
        # 6/5, 6/8 (val), 6/9 (null)
        closes=[66588.12, 64024.6, None],
        gmt_offset=32400,
    )
    bars = markets._parse_yahoo_chart_all_bars("^nkx", payload)
    _check(
        "f1 all_bars: non-null のみを asc date で返す",
        bars == [
            {"symbol": "^nkx", "date": "2026-06-05", "close": 66588.12},
            {"symbol": "^nkx", "date": "2026-06-08", "close": 64024.6},
        ],
        f"got {bars}",
    )


def test_all_bars_empty_on_all_null():
    payload = _yahoo_payload(
        timestamps=[1780617600, 1780876800],
        closes=[None, None],
        gmt_offset=32400,
    )
    bars = markets._parse_yahoo_chart_all_bars("^nkx", payload)
    _check("f2 all_bars: 全 null → []", bars == [], f"got {bars}")


def test_all_bars_empty_on_parse_error():
    bars = markets._parse_yahoo_chart_all_bars("xyz", "not json")
    _check("f3 all_bars: parse error → []", bars == [])


def test_fetch_all_markets_backfills_missing_history():
    """C68 第二弾 真因テスト：rmp fallback で current_date が 6/9 になっても
    bar の 6/8 を history に backfill するので compute_diff_pct が正しく
    6/8 を prior に選び、6/5 比較にならない。
    """
    # 5/29 (Fri) 既存 history、6/8 (Mon) bar=val、6/9 (Tue) bar=null + rmp 6/9
    payload = _yahoo_payload(
        timestamps=[1780876800, 1780963200],  # 6/8, 6/9 JST
        closes=[64024.6, None],
        gmt_offset=32400,
        regular_market_price=65416.63,
        regular_market_time=1780987503,  # 2026-06-09 15:45 JST
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "h.json"
        # 既存 history: 5/29 のみ（6/8 が抜けてる状況を再現）
        path.write_text(json.dumps({
            "^nkx": [{"date": "2026-05-29", "close": 66329.5}],
        }, ensure_ascii=False))

        # urlopen を 1 symbol だけ mock。^nkx 以外は payload を return しない
        # ような fake を組まないと SYMBOLS 全 5 件で叩く。簡単のため fetch
        # 単体（fetch_market_close）+ 手動 backfill ループを再現する。
        orig = _install_mock_urlopen(text=payload)
        try:
            fetched = markets.fetch_market_close("^nkx")
            # fetch_all_markets と同じロジックでバックフィル
            for bar in fetched.get("all_bars") or ():
                if bar["date"] >= fetched["date"]:
                    continue
                markets.append_history_entry(
                    "^nkx", date=bar["date"], close=bar["close"],
                    history_path=path,
                )
            diff = markets.compute_diff_pct(
                "^nkx", current_date=fetched["date"],
                current_close=fetched["close"], history_path=path,
            )
        finally:
            _restore_urlopen(orig)

    expected_diff = (65416.63 - 64024.6) / 64024.6 * 100  # +2.174...
    ok = (
        fetched is not None
        and fetched["date"] == "2026-06-09"
        and abs(fetched["close"] - 65416.63) < 1e-6
        and diff is not None
        and abs(diff - expected_diff) < 0.01
    )
    _check(
        "f4 fetch_all_markets: 6/8 が history に無くても all_bars で backfill "
        "→ diff は 6/8 比較で +2.17%",
        ok,
        f"got fetched={fetched} diff={diff}",
    )


def test_fetch_all_markets_writes_all_bars_to_history():
    """fetch_all_markets 経由で複数 bar が history に書かれることを統合検証."""
    payload = _yahoo_payload(
        timestamps=[1780617600, 1780876800, 1780963200],
        closes=[66588.12, 64024.6, None],
        gmt_offset=32400,
        regular_market_price=65416.63,
        regular_market_time=1780987503,  # 2026-06-09 15:45 JST
    )
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "h.json"
        orig = _install_mock_urlopen(text=payload)
        try:
            # SYMBOLS 全件で同じ payload を返すが、^nkx だけチェック
            results = markets.fetch_all_markets(history_path=path)
        finally:
            _restore_urlopen(orig)
        h = markets.load_history(path=path)

    nkx_dates = sorted(e["date"] for e in h.get("^nkx", []))
    _check(
        "f5 fetch_all_markets: 6/5 / 6/8 / 6/9 すべて history に書かれる",
        nkx_dates == ["2026-06-05", "2026-06-08", "2026-06-09"],
        f"got nkx dates = {nkx_dates}",
    )


def main() -> int:
    print("Markets (Stooq) tests — Sprint 5 task #2")
    print()
    print("(a) _parse_csv_line:")
    test_parse_yahoo_chart_normal()
    test_parse_yahoo_chart_trailing_null_skipped()
    test_parse_yahoo_chart_all_null()
    test_parse_yahoo_chart_error_field()
    test_parse_yahoo_chart_empty_result()
    test_parse_yahoo_chart_malformed_json()
    test_yahoo_symbol_mapping()
    test_parse_yahoo_uses_exchange_local_date()
    test_parse_yahoo_rmp_fallback_when_latest_bar_is_null()
    test_parse_yahoo_rmp_ignored_when_older_than_latest_bar()
    test_parse_yahoo_rmp_used_when_bar_all_null()
    test_parse_yahoo_no_rmp_no_bar_returns_none()
    print()
    print("(b) fetch_market_close:")
    test_fetch_market_close_success()
    test_fetch_market_close_network_error()
    test_fetch_market_close_unknown_symbol()
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
    test_format_forex_no_diff()
    test_format_forex_with_positive_diff()
    test_format_forex_with_negative_diff()
    test_format_no_data()
    print()
    print("(f) C68 第二弾 (2026-06-10): all_bars + history backfill:")
    test_all_bars_returns_non_null_in_date_order()
    test_all_bars_empty_on_all_null()
    test_all_bars_empty_on_parse_error()
    test_fetch_all_markets_backfills_missing_history()
    test_fetch_all_markets_writes_all_bars_to_history()
    print()
    print(f"=== {PASS} passed, {FAIL} failed ===")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
