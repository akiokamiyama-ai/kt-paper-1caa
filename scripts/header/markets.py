"""Yahoo Finance v8 chart client + local close-price cache for masthead-data row 2.

Sprint 5 task #2 (2026-05-04) で Stooq の無料 CSV (``/q/l/?...&e=csv``) を採用、
直近の終値を取得して ``logs/market_history.json`` に蓄積していた。

C66 (Sprint 9, 2026-06-08) — Stooq が JavaScript PoW (SHA-256) チャレンジを
全 endpoint に展開し、Mozilla/5.0 UA で叩いても HTML を返す挙動に変わった。
6/6 朝刊で日経以外が「―」、6/7 朝刊で全 fail → row 2 完全消失という症状の
真因。Stooq 復活待ちでは紙面の重要要素が無期限欠落するため、Yahoo Finance
v8 chart API (``query1.finance.yahoo.com/v8/finance/chart/<symbol>``) に
切替。Yahoo は無料・無認証で公開、GHA cron からは rate limit に当たりにくい。

history キャッシュは Stooq 時代の内部 ``symbol`` キー（``^nkx`` 等）をその
まま使い、後方互換を維持（過去 30 日分の close は再利用、Yahoo シンボルへの
マッピングは fetch 時のみに使う）。

前日比 (Δ%) はローカルキャッシュ方式：
1. 各ランで取得した ``{date, close}`` を ``logs/market_history.json`` に
   append（同 date は重複防止で skip、直近 30 日分だけ保持）。
2. 翌ランで「current_date より古い最新エントリ」の close との差分を計算。
3. 履歴が無いソース（初回ラン等）は diff=None → 表示「(-)」。

外部 API は Tribune の cost cap 集計外（無料）。
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from datetime import date as _date_type
from datetime import datetime, timezone
from pathlib import Path

YAHOO_BASE = "https://query1.finance.yahoo.com/v8/finance/chart"
YAHOO_DEFAULT_RANGE = "5d"   # 直近 5 営業日を取り、最後の non-null close を採用
YAHOO_DEFAULT_INTERVAL = "1d"
TIMEOUT_SEC = 5
HISTORY_KEEP_DAYS = 30

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
LOG_DIR = PROJECT_ROOT / "logs"
HISTORY_PATH = LOG_DIR / "market_history.json"

# 取得対象。内部 ``symbol`` キーは Stooq 時代から後方互換のため不変。
# Yahoo Finance 呼び出し時のみ ``yahoo_symbol`` を使う。
#   日経平均: ^N225 / NY ダウ: ^DJI / S&P 500: ^GSPC
#   USD/JPY: JPY=X (Yahoo は逆向き表記) / EUR/JPY: EURJPY=X
SYMBOLS: tuple[dict, ...] = (
    {"symbol": "^nkx",   "yahoo_symbol": "^N225",    "label": "日経",
     "kind": "index", "css_class": "market-nikkei"},
    {"symbol": "^dji",   "yahoo_symbol": "^DJI",     "label": "NYダウ",
     "kind": "index", "css_class": "market-dji"},
    {"symbol": "^spx",   "yahoo_symbol": "^GSPC",    "label": "S&P 500",
     "kind": "index", "css_class": "market-spx"},
    {"symbol": "usdjpy", "yahoo_symbol": "JPY=X",    "label": "USD",
     "kind": "forex", "css_class": "forex-usd"},
    {"symbol": "eurjpy", "yahoo_symbol": "EURJPY=X", "label": "EUR",
     "kind": "forex", "css_class": "forex-eur"},
)


def _yahoo_symbol_for(symbol: str) -> str | None:
    for s in SYMBOLS:
        if s["symbol"] == symbol:
            return s["yahoo_symbol"]
    return None


def fetch_market_close(symbol: str, *, timeout: int = TIMEOUT_SEC) -> dict | None:
    """Fetch the most recent close for the configured ``symbol``.

    Internally maps to ``yahoo_symbol`` and calls Yahoo Finance v8 chart API.
    Returns the Stooq-style shape for history backward compatibility:

    Returns
    -------
    dict | None
        ``{"symbol": "^nkx", "date": "2026-05-01", "close": 59513.12}``
        on success, ``None`` on any failure (network / parse / no data).
    """
    yahoo_sym = _yahoo_symbol_for(symbol)
    if yahoo_sym is None:
        print(f"  [markets] unknown symbol {symbol!r}", file=sys.stderr)
        return None
    url = (
        f"{YAHOO_BASE}/{urllib.parse.quote(yahoo_sym, safe='^=')}"
        f"?range={YAHOO_DEFAULT_RANGE}&interval={YAHOO_DEFAULT_INTERVAL}"
    )
    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (X11; Linux x86_64) kt-tribune/0.7"
                ),
                "Accept": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            text = resp.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, TimeoutError) as e:
        print(f"  [markets] FAIL {symbol}: {type(e).__name__}", file=sys.stderr)
        return None

    # C80d (Fable review M7): 旧仕様は _parse_yahoo_chart と
    # _parse_yahoo_chart_all_bars でそれぞれ json.loads + 抽出を独立に行い、
    # 同一 text を 2 回 parse + 同じ切り出しロジック重複していた。
    # _extract_chart_data に集約して 1 回 parse、current + all_bars を導出。
    data = _extract_chart_data(symbol, text, verbose=True)
    if data is None:
        return None
    current = _pick_current(symbol, data)
    if current is None:
        return None
    # C68 第二弾: 全 bar を ``all_bars`` として同梱、``fetch_all_markets`` が
    # history に逐次書き込んで欠損日を自動補填する。
    return {**current, "all_bars": data["bars"]}


def _local_date(ts: int, gmt_offset_sec: int) -> str:
    """Convert a unix ts to ISO date in the exchange's local timezone."""
    from datetime import timedelta
    tz = timezone(timedelta(seconds=gmt_offset_sec))
    return datetime.fromtimestamp(ts, tz=tz).date().isoformat()


def _extract_chart_data(symbol: str, text: str, *, verbose: bool = False) -> dict | None:
    """Yahoo chart JSON を 1 回パスで分解、共通中間表現を返す.

    C80d (Sprint 9, 2026-06-12, Fable review M7): Sprint 9 まで
    ``_parse_yahoo_chart`` と ``_parse_yahoo_chart_all_bars`` で同じ text を
    2 回 ``json.loads`` し、gmtoffset / timestamps / closes の切り出しと
    truncate ロジックも重複していた。本ヘルパーで JSON parse + bar 抽出を
    1 回に集約。``fetch_market_close`` は本関数を 1 回呼んで current +
    all_bars を同時に組み立てる。

    防御強化（Fable M7）: ``indicators.quote[0]`` が ``None`` の場合
    （Yahoo の障害時に観測される）``AttributeError`` を出さず空 ``bars``
    として扱う。

    Returns
    -------
    dict | None
        ``{"meta": dict, "gmt_offset": int, "bars": list[dict]}`` または
        パース不能・データなし時に ``None``。``bars`` は non-null close のみ、
        date 昇順、各要素は ``{"symbol", "date", "close"}``。

    Parameters
    ----------
    verbose :
        True の場合、parse error / Yahoo API error を stderr に出力する
        （``_parse_yahoo_chart`` 経由のみ true、``_parse_yahoo_chart_all_bars``
        は静かに失敗する後方互換）。
    """
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        if verbose:
            print(f"  [markets] parse error for {symbol}: {e}", file=sys.stderr)
        return None
    chart = data.get("chart") or {}
    err = chart.get("error")
    if err:
        if verbose:
            print(f"  [markets] yahoo error for {symbol}: {err}", file=sys.stderr)
        return None
    results = chart.get("result") or []
    if not results:
        return None
    r0 = results[0]
    meta = r0.get("meta") or {}
    try:
        gmt_offset = int(meta.get("gmtoffset") or 0)
    except (TypeError, ValueError):
        gmt_offset = 0
    timestamps = r0.get("timestamp") or []
    indicators = r0.get("indicators") or {}
    quotes = indicators.get("quote") or []
    # M7 防御: quotes[0] が None / 非 dict の場合に AttributeError を出さない
    if quotes and isinstance(quotes[0], dict):
        closes = quotes[0].get("close") or []
    else:
        closes = []
    if len(closes) != len(timestamps):
        n = min(len(closes), len(timestamps))
        timestamps = timestamps[:n]
        closes = closes[:n]
    bars: list[dict] = []
    for ts, c in zip(timestamps, closes):
        if c is None:
            continue
        try:
            bars.append({
                "symbol": symbol,
                "date": _local_date(int(ts), gmt_offset),
                "close": float(c),
            })
        except (TypeError, ValueError, OSError):
            continue
    bars.sort(key=lambda e: e["date"])
    return {"meta": meta, "gmt_offset": gmt_offset, "bars": bars}


def _pick_current(symbol: str, data: dict) -> dict | None:
    """``_extract_chart_data`` の結果から「current = 末尾 bar + rmp fallback」を導出.

    C80d M7: ``_parse_yahoo_chart`` と ``fetch_market_close`` で同じ rmp
    fallback ロジックを書き出していたのを集約。
    """
    bars: list[dict] = data["bars"]
    meta: dict = data["meta"]
    gmt_offset: int = data["gmt_offset"]
    bar_close = bars[-1] if bars else None
    # C68 fix: regularMarketPrice が bar より新しければそちらを採用
    rmp_raw = meta.get("regularMarketPrice")
    rmt_raw = meta.get("regularMarketTime")
    if rmp_raw is not None and rmt_raw is not None:
        try:
            rmp_val = float(rmp_raw)
            rmt_int = int(rmt_raw)
            rmp_date = _local_date(rmt_int, gmt_offset)
            if bar_close is None or rmp_date > bar_close["date"]:
                return {"symbol": symbol, "date": rmp_date, "close": rmp_val}
        except (TypeError, ValueError, OSError):
            pass
    return bar_close


def _parse_yahoo_chart_all_bars(symbol: str, text: str) -> list[dict]:
    """Return all non-null bar closes as ``[{date, close}, ...]`` (asc by date).

    C68 第二弾 fix (Sprint 9, 2026-06-10): Yahoo は範囲内の日次バーを返すが、
    ``_parse_yahoo_chart`` は **末尾の 1 点だけ** を返していたため、欠損日の
    値が後から fill された際に history へ反映されず、``compute_diff_pct`` が
    「最後に書かれた日」を prior として使ってしまう（6/8 月曜 bar が 6/9 cron
    時は null、6/10 cron 時に 64024.6 で埋まったが history には ^nkx 6/8 が
    永久に欠落 → 6/10 朝刊 diff が 6/5 比較で -1.8% と誤表示された C68 残バグ）。
    本関数は **全 non-null bar** を返す。``fetch_all_markets`` が history に
    逐次 append することで欠損日が翌日 cron で自動補填される。

    C80d (Fable review M7): 内部実装を ``_extract_chart_data`` 経由に統合。
    """
    data = _extract_chart_data(symbol, text)
    return data["bars"] if data else []


def _parse_yahoo_chart(symbol: str, text: str) -> dict | None:
    """Parse Yahoo Finance v8 chart JSON. Returns ``{symbol, date, close}`` or None.

    Yahoo chart レスポンスは ``chart.result[0]`` に ``timestamp`` 配列と
    ``indicators.quote[0].close`` 配列を持つ（同インデックスで対応）。
    Yahoo は欠損日に null を返すため、**末尾から遡って最初の non-null close**
    を採用する。

    Date は **exchange のローカル timezone** (``meta.gmtoffset``) で日付に
    変換する。UTC date 直行だと exchange timezone の境界で off-by-one が
    起き得る（^DJI 等の bar timestamp は 09:30 NY = 13:30 UTC で偶然合うが、
    将来の symbol 追加でズレるリスクがある）。

    C68 fix (Sprint 9, 2026-06-09): Nikkei (^N225) の 6/8 月曜 bar.close が
    Yahoo 側で None 配信される（数時間遅延、引け後でも更新されない）。
    一方 ``meta.regularMarketPrice`` + ``meta.regularMarketTime`` には引け値
    (64024.6, 15:45 JST) が即時反映されている。bar 走査の後、regularMarketPrice
    の date が bar.date より新しければそちらを採用するフォールバックを追加。
    神山さん要望「日本市場は前日夜のものを見たい」に応える。

    C80d (Fable review M7): 内部実装を ``_extract_chart_data`` + ``_pick_current``
    経由に統合。
    """
    data = _extract_chart_data(symbol, text, verbose=True)
    if data is None:
        return None
    return _pick_current(symbol, data)


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
    """Atomically write the history JSON.

    C80c (Sprint 9, 2026-06-12, Fable review H4): 旧仕様は ``open(p, "w")``
    直書きで、途中 kill / OOM / GHA timeout（90 分）の最中に中断されると
    JSON が半端な状態になり得た。``load_history`` は破損時に ``{}`` を返す
    ため、**次の save で 30 日分の履歴が無言で全消失** するシナリオがあった
    （C68 第二弾の all_bars backfill で 1 ran ~25 回の write が走る、
    GHA に concurrency ガードなし）。tmp ファイルに書き出して
    ``os.replace`` で同一 fs 上に atomic rename することで、`history.json`
    は常に「**ひとつ前の有効な状態** か **新しい有効な状態**」のいずれかに
    保たれる（POSIX rename atomicity）。
    """
    p = path or HISTORY_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    # 同一ディレクトリに tmp を作って rename を同 fs に保つ（cross-fs だと
    # os.replace は fallback として copy + unlink になり atomic 性が崩れる）。
    fd = tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8",
        dir=str(p.parent),
        prefix=p.name + ".", suffix=".tmp",
        delete=False,
    )
    tmp_path = fd.name
    try:
        try:
            json.dump(history, fd, ensure_ascii=False, indent=2)
            fd.flush()
            os.fsync(fd.fileno())
        finally:
            fd.close()
        os.replace(tmp_path, p)
    except Exception:
        # rename 失敗時は tmp を clean up（atomic rename 直前で書き込み失敗）。
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _merge_entry_in_memory(
    history: dict,
    symbol: str,
    *,
    date: str,
    close: float,
    keep_days: int = HISTORY_KEEP_DAYS,
) -> None:
    """``append_history_entry`` の I/O-less 版（C80c, Fable review H4 + B）.

    save しないので、複数 symbol × 複数 bar を一括 merge してから 1 回
    ``save_history`` する用途で使う。Same-date entry は first-write wins
    で skip（intra-day 重複保護）。``keep_days`` 超過は古い方から削る。

    First-write-wins の意味論（C80d, Fable review M3）
    -----------------------------------------------
    GHA cron は 02:37 JST に走るが、これは取引所により「同 date でも違う
    瞬間のスナップショット」を取ることを意味する：

    - ^nkx（東京証券取引所、JST）: 15:00 JST 引け後 → 02:37 JST 翌日 = 真の引け値
    - ^dji / ^spx（NYSE、ET）: 02:37 JST = **13:37 ET（場中スナップショット）**
    - JPY=X / EURJPY=X（24h 為替）: 02:37 JST のレート（中間値）

    米国系 (^dji / ^spx) は same-date skip により **当日の場中値が「確定値」
    として履歴に残り、翌日 all_bars で確定 close を取り直しても上書きされない**
    （Fable review M3 指摘）。同時刻同士の比較として自己整合的だが、C68 第二弾
    の「欠損日を補填して正しい prior を選ぶ」意図とは別レイヤー：history は
    「定刻 02:37 JST 時点のその symbol のスナップショット系列」として
    解釈する。確定値への収束を求める場合は別 mechanism（例：閉場後に再 fetch
    する米国系専用 cron、または same-date 上書き許可フラグ）が必要。
    """
    entries: list = list(history.get(symbol, []))
    if any(e.get("date") == date for e in entries):
        history[symbol] = entries
        return
    entries.append({"date": date, "close": close})
    entries.sort(key=lambda e: e.get("date", ""))
    if len(entries) > keep_days:
        entries = entries[-keep_days:]
    history[symbol] = entries


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

    C80c: I/O-less な merge は ``_merge_entry_in_memory`` を使う。本関数は
    単発書き込みとして save まで行う既存 API を維持（テスト・単体呼び出し用）。
    ``fetch_all_markets`` は本関数を使わず in-memory merge + 1 save に集約。
    """
    history = load_history(path=history_path)
    _merge_entry_in_memory(
        history, symbol, date=date, close=close, keep_days=keep_days,
    )
    save_history(history, path=history_path)
    return history


def _compute_diff_pct_from_history(
    history: dict,
    symbol: str,
    *,
    current_date: str,
    current_close: float,
) -> float | None:
    """``compute_diff_pct`` の I/O-less 版（C80c）.

    既に load 済の history dict から prior を引き当てる。``fetch_all_markets``
    の 1 ran 1 save 集約用。
    """
    entries = history.get(symbol, [])
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
    return _compute_diff_pct_from_history(
        history, symbol,
        current_date=current_date, current_close=current_close,
    )


def format_market_value(meta: dict, fetched: dict | None, diff_pct: float | None) -> str:
    """Format one market display string for the masthead.

    Examples
    --------
    >>> format_market_value({"label":"日経","kind":"index"}, {"close":38420}, 0.5)
    '日経 38,420 (+0.5%)'
    >>> format_market_value({"label":"USD","kind":"forex"}, {"close":152.10}, 0.3)
    'USD 152.10 (+0.45円)'
    >>> format_market_value({"label":"USD","kind":"forex"}, {"close":152.10}, None)
    'USD 152.10 (-)'
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
        # 為替は円換算で前日比表示（％より体感に近い、5/20 神山さん観察 C15）。
        # diff_pct から前日 close を逆算し、差分を円で表示する。
        #   diff_pct = (close - prior) / prior * 100
        #   → prior = close / (1 + diff_pct/100), diff_yen = close - prior
        if diff_pct is None:
            return f"{label} {close:,.2f} (-)"
        prior = close / (1 + diff_pct / 100)
        diff_yen = close - prior
        sign = "+" if diff_yen >= 0 else ""
        return f"{label} {close:,.2f} ({sign}{diff_yen:.2f}円)"
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
    # C80c (Sprint 9, 2026-06-12, Fable review H4 + B): 1 ran 1 save に集約。
    # 旧仕様は per-bar / per-symbol で append_history_entry → save_history を
    # 呼び、5 symbol × (最大 4 backfill + 1 current) ≒ 25 回の write/ran が
    # 走っていた。本実装では load 1 回 + in-memory merge + save 1 回 に集約し、
    # write 1 回/ran + atomic rename で破損リスクを最小化する。
    history = load_history(path=history_path)

    for meta in SYMBOLS:
        symbol = meta["symbol"]
        fetched = fetch_market_close(symbol)
        diff_pct: float | None = None
        if fetched:
            # C68 第二弾 (2026-06-10): 全 bar を **diff 計算前に** history へ
            # 書き込む。これで「過去の欠損日（Yahoo bar が null だった日）」が
            # 後日 fill された際に翌日 cron で自動補填され、``_compute_diff_pct``
            # が正しい prior（直近の前日 close）を選べる。
            # ``_merge_entry_in_memory`` は同 date を skip するので冪等。
            current_date = fetched["date"]
            for bar in fetched.get("all_bars") or ():
                bar_date = bar.get("date")
                if bar_date is None or bar_date >= current_date:
                    # current_date 以降は下の merge で書く（または skip）
                    continue
                _merge_entry_in_memory(
                    history, symbol,
                    date=bar_date, close=bar["close"],
                )
            diff_pct = _compute_diff_pct_from_history(
                history, symbol,
                current_date=current_date,
                current_close=fetched["close"],
            )
            _merge_entry_in_memory(
                history, symbol,
                date=current_date, close=fetched["close"],
            )
        out.append({
            "meta": meta,
            "fetched": fetched,
            "diff_pct": diff_pct,
        })

    # C80c: 全 symbol の merge 完了後に 1 回だけ atomic save。途中 1 symbol
    # が失敗しても他 symbol の merge 結果は保たれる。save 自体の失敗は
    # log のみで握り潰し（次 ran で再試行）、ランナーの紙面生成を止めない。
    try:
        save_history(history, path=history_path)
    except Exception as e:
        print(
            f"  [markets] consolidated history save failed: "
            f"{type(e).__name__}: {e}",
            file=sys.stderr,
        )
    return out
