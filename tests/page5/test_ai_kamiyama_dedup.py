"""第5面 AIかみやま の自己 dedup (C168, Sprint 13, 2026-08-17).

背景
----
5 面は長らく**唯一 dedup を持たない面**だった。C40 第二弾 (2026-05-30) が
「候補は当日確定紙面のみなので、他面の dedup に相乗りすれば連続日重複は
自動解決する」と設計したためである。

C167 調査でこの前提が誤りと判明した。archive 全期間（2026-04-25〜08-17、
5 面参照記事 100 ユニーク URL）で日跨ぎ重複は **6 件**:

    5/22→5/23  5/29→5/30  6/20→6/21  7/02→7/05  8/03→8/04  （C155 前）
    8/14→8/17                                               （C161 後）

他面の dedup 窓（page3 7 日）を超えた記事が候補に戻るため相乗りでは防げない。
さらに C161 で候補が page3 runner-up のみになり、runner-up は ``page3_urls``
に記録されないので**どの面の dedup にも引っかからなくなった**。

Tests:
  a) 過去 N 日に出た URL が候補から除外される
  b) 除外後 0 件なら除外を諦める（白紙より重複）+ WARN
  c) 除外窓の境界（N 日前は除外 / N+1 日前は許可）
  d) exclude_urls 未指定なら従来動作（後方互換）
  e) 定数と配線
  f) 8/14→8/17 の実事象が防げること（回帰テスト）

Run::

    python3 -m tests.page5.test_ai_kamiyama_dedup
"""

from __future__ import annotations

import io
import json
import random
import sys
import tempfile
from contextlib import redirect_stderr
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

from scripts.page5.ai_kamiyama_selector import select_ai_kamiyama_article

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


def _art(url: str, score: float = 50.0) -> dict:
    return {"url": url, "title": f"T {url[-6:]}", "source_name": "S",
            "description": "d", "final_score": score}


def _pick(runner_ups, exclude=None, seed=0, top_n=5):
    return select_ai_kamiyama_article(
        target_date=date(2026, 8, 18),
        page3_runner_ups=runner_ups,
        exclude_urls=exclude,
        rng=random.Random(seed),
        top_n=top_n,
    )


# ---------------------------------------------------------------------------
# (a) 除外が効く
# ---------------------------------------------------------------------------

def test_excluded_url_never_picked():
    ru = [_art(f"https://x/{i}", 100 - i) for i in range(10)]
    excluded = {"https://x/0", "https://x/1", "https://x/2"}
    picks = {_pick(ru, excluded, seed=s)["url"] for s in range(60)}
    _check("a1 除外 URL は 60 seed 試行で一度も選ばれない",
           not (picks & excluded), f"got {sorted(picks & excluded)}")
    _check("a2 除外後の上位から選ばれている",
           picks <= {f"https://x/{i}" for i in range(3, 8)}, f"got {sorted(picks)}")


def test_top_n_shifts_after_exclusion():
    """除外で順位が繰り上がり、6-8 位だった記事が候補入りする."""
    ru = [_art(f"https://x/{i}", 100 - i) for i in range(10)]
    without = {_pick(ru, None, seed=s)["url"] for s in range(60)}
    with_ex = {_pick(ru, {f"https://x/{i}" for i in range(5)}, seed=s)["url"]
               for s in range(60)}
    _check("a3 除外なしなら上位 5 件から選ばれる",
           without <= {f"https://x/{i}" for i in range(5)}, f"got {sorted(without)}")
    _check("a4 上位 5 件を除外すると次の 5 件から選ばれる",
           with_ex <= {f"https://x/{i}" for i in range(5, 10)}, f"got {sorted(with_ex)}")


def test_exclusion_logs_removed_count():
    ru = [_art(f"https://x/{i}", 100 - i) for i in range(10)]
    buf = io.StringIO()
    with redirect_stderr(buf):
        _pick(ru, {"https://x/0", "https://x/1"})
    _check("a5 除外件数が stderr に出る（可視化）",
           "2 件を候補から除外" in buf.getvalue(), buf.getvalue()[:70])


# ---------------------------------------------------------------------------
# (b) 除外後 0 件の fallback
# ---------------------------------------------------------------------------

def test_all_excluded_falls_back():
    """全候補が既出なら除外を諦める（白紙より重複、C161 と同じ思想）."""
    ru = [_art(f"https://x/{i}", 100 - i) for i in range(3)]
    allx = {f"https://x/{i}" for i in range(3)}
    buf = io.StringIO()
    with redirect_stderr(buf):
        got = _pick(ru, allx)
    _check("b1 除外後 0 件でも None にならない（紙面を落とさない）",
           got is not None and got["url"] in allx, f"got {got}")
    _check("b2 WARN が stderr に出る",
           "WARN" in buf.getvalue() and "除外を諦め" in buf.getvalue(),
           buf.getvalue()[:90])


def test_partial_exclusion_no_warn():
    ru = [_art(f"https://x/{i}", 100 - i) for i in range(5)]
    buf = io.StringIO()
    with redirect_stderr(buf):
        _pick(ru, {"https://x/0"})
    _check("b3 一部除外では WARN を出さない", "WARN" not in buf.getvalue())


def test_empty_pool_still_none():
    _check("b4 候補ゼロなら従来どおり None",
           _pick([], {"https://x/0"}) is None)


# ---------------------------------------------------------------------------
# (c) 除外窓の境界
# ---------------------------------------------------------------------------

def _write_log(dirpath: Path, d: date, page5_url: str | None) -> None:
    (dirpath / f"displayed_urls_{d.isoformat()}.json").write_text(
        json.dumps({"date": d.isoformat(), "page1_urls": [], "page2_urls": {},
                    "page3_urls": [], "page4_urls": [], "page5_url": page5_url,
                    "page6_urls": {}, "headlines_urls": []}, ensure_ascii=False),
        encoding="utf-8",
    )


def test_window_boundary():
    """N 日前は除外、N+1 日前は許可（境界の固定）."""
    from scripts.selector import dedup_filter
    from scripts.regen_front_page_v2 import PAGE5_DEDUP_DAYS

    target = date(2026, 8, 18)
    with tempfile.TemporaryDirectory() as td:
        p = Path(td)
        inside = target - timedelta(days=PAGE5_DEDUP_DAYS)
        outside = target - timedelta(days=PAGE5_DEDUP_DAYS + 1)
        _write_log(p, inside, "https://inside/")
        _write_log(p, outside, "https://outside/")
        with patch.object(dedup_filter, "LOG_DIR", p):
            got = dedup_filter.load_recently_displayed_urls(
                PAGE5_DEDUP_DAYS, page="page5", until_date=target,
            )
    _check(f"c1 {PAGE5_DEDUP_DAYS} 日前の URL は除外対象",
           "https://inside/" in got, f"got {sorted(got)}")
    _check(f"c2 {PAGE5_DEDUP_DAYS + 1} 日前の URL は対象外",
           "https://outside/" not in got, f"got {sorted(got)}")


def test_target_day_itself_not_excluded():
    """当日は窓に含まない（自分の選定を除外しない）."""
    from scripts.selector import dedup_filter
    from scripts.regen_front_page_v2 import PAGE5_DEDUP_DAYS

    target = date(2026, 8, 18)
    with tempfile.TemporaryDirectory() as td:
        p = Path(td)
        _write_log(p, target, "https://today/")
        with patch.object(dedup_filter, "LOG_DIR", p):
            got = dedup_filter.load_recently_displayed_urls(
                PAGE5_DEDUP_DAYS, page="page5", until_date=target,
            )
    _check("c3 当日の page5_url は除外対象に入らない",
           "https://today/" not in got, f"got {sorted(got)}")


# ---------------------------------------------------------------------------
# (d) 後方互換
# ---------------------------------------------------------------------------

def test_none_exclude_is_noop():
    ru = [_art(f"https://x/{i}", 100 - i) for i in range(10)]
    a = {_pick(ru, None, seed=s)["url"] for s in range(30)}
    b = {_pick(ru, set(), seed=s)["url"] for s in range(30)}
    _check("d1 exclude_urls=None と空集合で挙動が同じ", a == b, f"{sorted(a)} vs {sorted(b)}")
    _check("d2 除外なしなら上位 5 件のみ",
           a <= {f"https://x/{i}" for i in range(5)}, f"got {sorted(a)}")


# ---------------------------------------------------------------------------
# (e) 定数と配線
# ---------------------------------------------------------------------------

def test_constant_and_wiring():
    import inspect
    from scripts.regen_front_page_v2 import PAGE5_DEDUP_DAYS, build_page_five_v2

    _check("e1 PAGE5_DEDUP_DAYS が実用値", 1 <= PAGE5_DEDUP_DAYS <= 60,
           f"got {PAGE5_DEDUP_DAYS}")
    _check("e2 3 面の窓（7 日）と揃えてある", PAGE5_DEDUP_DAYS == 7,
           f"got {PAGE5_DEDUP_DAYS}")
    src = inspect.getsource(build_page_five_v2)
    _check("e3 build_page_five_v2 が page5 の過去 URL を読む",
           'page="page5"' in src and "PAGE5_DEDUP_DAYS" in src)
    _check("e4 selector に exclude_urls を渡している", "exclude_urls=" in src)


def test_selector_accepts_exclude_urls():
    import inspect
    sig = inspect.signature(select_ai_kamiyama_article)
    _check("e5 select API が exclude_urls を受ける",
           "exclude_urls" in sig.parameters)


# ---------------------------------------------------------------------------
# (f) 実事象の回帰テスト
# ---------------------------------------------------------------------------

def test_regression_8_14_to_8_17():
    """8/14 に出た URL が 8/17 の候補から除外されること（C167 の実事象）."""
    url = "https://thepointmag.com/politics/we-were-the-99-percent/"
    # 8/17 の候補プール再現（当該 URL は第 4 位相当）
    ru = [_art("https://other/1", 78), _art("https://other/2", 76),
          _art("https://other/3", 74), _art(url, 73.1),
          _art("https://other/4", 72), _art("https://other/5", 71)]
    picks = {_pick(ru, {url}, seed=s)["url"] for s in range(60)}
    _check("f1 8/14 採用 URL は 8/17 の候補から外れる",
           url not in picks, f"got {sorted(picks)}")
    _check("f2 代わりに 5 位以下が繰り上がって選ばれる",
           "https://other/5" in picks or "https://other/4" in picks,
           f"got {sorted(picks)}")


def main() -> int:
    print("第5面 自己 dedup tests (C168, Sprint 13, 2026-08-17)")
    print()
    print("(a) 除外が効く:")
    test_excluded_url_never_picked()
    test_top_n_shifts_after_exclusion()
    test_exclusion_logs_removed_count()
    print()
    print("(b) 除外後 0 件の fallback:")
    test_all_excluded_falls_back()
    test_partial_exclusion_no_warn()
    test_empty_pool_still_none()
    print()
    print("(c) 除外窓の境界:")
    test_window_boundary()
    test_target_day_itself_not_excluded()
    print()
    print("(d) 後方互換:")
    test_none_exclude_is_noop()
    print()
    print("(e) 定数と配線:")
    test_constant_and_wiring()
    test_selector_accepts_exclude_urls()
    print()
    print("(f) 実事象の回帰:")
    test_regression_8_14_to_8_17()
    print()
    print(f"=== {PASS} passed, {FAIL} failed ===")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
