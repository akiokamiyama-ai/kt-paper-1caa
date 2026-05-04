"""Stooq market client + local close-price cache for the masthead-data row 2.

Sprint 5 task #2 (2026-05-04). Stooq の無料 1行 CSV (``/q/l/?...&e=csv``) で
直近の終値を取得する。Stooq の history endpoint は API key 必須化された
ため、前日比 (Δ%) の計算は **ローカルキャッシュ方式** で行う：

1. 各ランで取得した ``{date, close}`` を ``logs/market_history.json`` に
   append（同 date は重複防止で skip、直近 30 日分だけ保持）。
2. 翌ランで「current_date より古い最新エントリ」の close との差分を計算。
3. 履歴が無いソース（初回ラン等）は diff=None → 表示「(-)」。

外部 API は Tribune の cost cap 集計外（無料）。
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from datetime import date as _date_type
from pathlib import Path

STOOQ_BASE = "https://stooq.com/q/l/"
TIMEOUT_SEC = 3
HISTORY_KEEP_DAYS = 30

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
LOG_DIR = PROJECT_ROOT / "logs"
HISTORY_PATH = LOG_DIR / "market_history.json"

# 取得対象。stooq symbol → 表示用メタ（label, kind, format）
SYMBOLS: tuple[dict, ...] = (
    {"symbol": "^nkx",   "label": "日経",      "kind": "index",
     "css_class": "market-nikkei"},
    {"symbol": "^dji",   "label": "NYダウ",   "kind": "index",
     "css_class": "market-dji"},
    {"symbol": "^spx",   "label": "S&P 500",   "kind": "index",
     "css_class": "market-spx"},
    {"symbol": "usdjpy", "label": "USD",       "kind": "forex",
     "css_class": "forex-usd"},
    {"symbol": "eurjpy", "label": "EUR",       "kind": "forex",
     "css_class": "forex-eur"},
)


def fetch_market_close(symbol: str, *, timeout: int = TIMEOUT_SEC) -> dict | None:
    """Fetch the most recent close for a stooq symbol.

    Returns
    -------
    dict | None
        ``{"symbol": "^nkx", "date": "2026-05-01", "close": 59513.12}``
        on success, ``None`` on any failure.
    """
    url = f"{STOOQ_BASE}?s={symbol}&f=sd2t2ohlcv&h&e=csv"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            text = resp.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, TimeoutError) as e:
        print(f"  [markets] FAIL {symbol}: {type(e).__name__}", file=sys.stderr)
        return None

    return _parse_csv_line(symbol, text)


def _parse_csv_line(symbol: str, text: str) -> dict | None:
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if len(lines) < 2:
        return None
    # First line is header, second is the data row
    fields = lines[1].split(",")
    if len(fields) < 7:
        return None
    try:
        symbol_returned = fields[0].strip()
        date_str = fields[1].strip()
        close_str = fields[6].strip()
        if not date_str or not close_str or close_str.upper() == "N/D":
            return None
        return {
            "symbol": symbol_returned,
            "date": date_str,
            "close": float(close_str),
        }
    except (ValueError, IndexError) as e:
        print(f"  [markets] parse error for {symbol}: {e}", file=sys.stderr)
        return None


# ---------------------------------------------------------------------------
# Local close-price cache (logs/market_history.json)
# ---------------------------------------------------------------------------

def load_history(*, path: Path | None = None) -> dict:
    """Load ``logs/market_history.json``. Returns empty dict on missing/corrupt."""
    p = path or HISTORY_PATH
    if not p.exists():
        return {}
    try:
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {}
        return data
    except (json.JSONDecodeError, OSError):
        return {}


def save_history(history: dict, *, path: Path | None = None) -> None:
    p = path or HISTORY_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


def append_history_entry(
    symbol: str,
    *,
    date: str,
    close: float,
    history_path: Path | None = None,
    keep_days: int = HISTORY_KEEP_DAYS,
) -> dict:
    """Append a {date, close} entry for ``symbol`` (skip if same-date dup).

    Prunes to the most recent ``keep_days`` entries per symbol.
    Returns the updated history dict.
    """
    history = load_history(path=history_path)
    entries: list = list(history.get(symbol, []))
    if any(e.get("date") == date for e in entries):
        # Same-date entry already present — keep existing (first-write wins
        # per day, prevents intra-day overwrites if multiple runs happen).
        history[symbol] = entries
        save_history(history, path=history_path)
        return history
    entries.append({"date": date, "close": close})
    # Sort by date ascending, prune to last keep_days
    entries.sort(key=lambda e: e.get("date", ""))
    if len(entries) > keep_days:
        entries = entries[-keep_days:]
    history[symbol] = entries
    save_history(history, path=history_path)
    return history


def compute_diff_pct(
    symbol: str,
    *,
    current_date: str,
    current_close: float,
    history_path: Path | None = None,
) -> float | None:
    """Compute the percent change from the most recent prior-date close.

    Returns
    -------
    float | None
        Percentage change (e.g. 0.5 means +0.5%). ``None`` when no prior
        entry exists (initial run).
    """
    history = load_history(path=history_path)
    entries = history.get(symbol, [])
    # Find the latest entry with date < current_date
    prior_entries = [e for e in entries if e.get("date", "") < current_date]
    if not prior_entries:
        return None
    prior_entries.sort(key=lambda e: e.get("date", ""))
    prior_close = prior_entries[-1].get("close")
    if not prior_close:
        return None
    try:
        return ((float(current_close) - float(prior_close)) / float(prior_close)) * 100.0
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def format_market_value(meta: dict, fetched: dict | None, diff_pct: float | None) -> str:
    """Format one market display string for the masthead.

    Examples
    --------
    >>> format_market_value({"label":"日経","kind":"index"}, {"close":38420}, 0.5)
    '日経 38,420 (+0.5%)'
    >>> format_market_value({"label":"USD","kind":"forex"}, {"close":152.10}, None)
    'USD 152.10'
    >>> format_market_value({"label":"日経","kind":"index"}, None, None)
    '日経 -'
    """
    label = meta.get("label", "")
    if not fetched:
        return f"{label} -"
    close = fetched.get("close")
    if close is None:
        return f"{label} -"
    if meta.get("kind") == "forex":
        # 為替は前日比省略、絶対値（小数2桁）のみ
        return f"{label} {close:,.2f}"
    # Index: カンマ区切り整数 + diff
    close_str = f"{close:,.0f}"
    if diff_pct is None:
        return f"{label} {close_str} (-)"
    sign = "+" if diff_pct >= 0 else ""
    return f"{label} {close_str} ({sign}{diff_pct:.1f}%)"


def fetch_all_markets(*, history_path: Path | None = None) -> list[dict]:
    """Fetch all configured symbols and compute diffs against local history.

    Side effect: appends each fetched (date, close) to history. Per-symbol
    failures are isolated; the returned list always has one entry per
    SYMBOLS row (with ``fetched=None`` and ``diff_pct=None`` on failure).
    """
    out: list[dict] = []
    for meta in SYMBOLS:
        symbol = meta["symbol"]
        fetched = fetch_market_close(symbol)
        diff_pct: float | None = None
        if fetched:
            diff_pct = compute_diff_pct(
                symbol,
                current_date=fetched["date"],
                current_close=fetched["close"],
                history_path=history_path,
            )
            try:
                append_history_entry(
                    symbol,
                    date=fetched["date"],
                    close=fetched["close"],
                    history_path=history_path,
                )
            except Exception as e:
                print(
                    f"  [markets] history write failed for {symbol}: "
                    f"{type(e).__name__}",
                    file=sys.stderr,
                )
        out.append({
            "meta": meta,
            "fetched": fetched,
            "diff_pct": diff_pct,
        })
    return out
