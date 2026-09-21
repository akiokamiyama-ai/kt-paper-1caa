"""第5面 一筆の観測ログ (C201, 2026-09-21).

このテストの要件
----------------
**本番経路を通したときに記録されること**を固定する。

C200 で見つかった穴は、``update_history_column_fields`` のテストが
**関数を直接呼ぶ**形だったこと。C155-2 (2026-08-10) が
``build_page_five_v2`` から呼び出しを落としても 6 本すべて green のままで、
42 日間 ``ai_kamiyama_called`` が false を書き続けた。

したがって (c)(d)(e) は ``regen_front_page_v2.build_page_five_v2`` を
実際に呼ぶ。miibo / Anthropic / selector は差し替えるが、
**記録の呼び出し自体は差し替えない**。ここを迂回するテストに直すと
同じ穴が戻る。

Run::

    python3 -m tests.page5.test_column_history
"""

from __future__ import annotations

import json
import sys
import tempfile
from datetime import date
from pathlib import Path

from scripts.page5 import column_history

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


_ARTICLE = {
    "url": "https://example.test/a1",
    "title": "Test Article",
    "title_ja": "テスト記事",
    "source_name": "Example",
    "pub_date": "2026-09-21",
}


def _column(*, called=True, failed=False, fallback=False, ms=1234, body="本文" * 50):
    return {
        "column_title": "見出し",
        "column_body": body,
        "is_fallback": fallback,
        "elapsed_ms": ms,
        "ai_kamiyama_called": called,
        "ai_kamiyama_failed": failed,
        "fallback_used": fallback,
    }


# ---------------------------------------------------------------------------
# (a) 記録の中身
# ---------------------------------------------------------------------------

def test_success_entry():
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "h.json"
        e = column_history.record_column_result(
            target_date=date(2026, 9, 21), article=_ARTICLE,
            column=_column(), path=p,
        )
        _check("a1 成功時 miibo_called=True / failed=False",
               e["miibo_called"] is True and e["miibo_failed"] is False)
        _check("a2 論評対象の URL が入る",
               e["article_url"] == "https://example.test/a1")
        _check("a3 本文字数を記録", e["column_body_chars"] == 100,
               str(e["column_body_chars"]))
        _check("a4 ファイルに 1 件書かれる",
               len(json.loads(p.read_text(encoding="utf-8"))["history"]) == 1)


def test_failure_entry():
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "h.json"
        e = column_history.record_column_result(
            target_date=date(2026, 9, 21), article=_ARTICLE,
            column=_column(failed=True, fallback=True, ms=0), path=p,
        )
        _check("a5 miibo 失敗が記録される",
               e["miibo_failed"] is True and e["fallback_used"] is True)
        _check("a6 recent_failures が拾う",
               len(column_history.recent_failures(path=p)) == 1)


def test_placeholder_entry():
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "h.json"
        e = column_history.record_column_result(
            target_date=date(2026, 9, 21), article=None, column=None, path=p,
        )
        _check("a7 休載は is_placeholder=True / miibo_called=False",
               e["is_placeholder"] is True and e["miibo_called"] is False)
        _check("a8 休載は失敗として数えない",
               len(column_history.recent_failures(path=p)) == 0)


# ---------------------------------------------------------------------------
# (b) 冪等性・頑健性
# ---------------------------------------------------------------------------

def test_same_date_upserts():
    """C185 と同じ思想：二重実行で 2 行にしない。"""
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "h.json"
        column_history.record_column_result(
            target_date=date(2026, 9, 21), article=_ARTICLE,
            column=_column(failed=True, fallback=True), path=p)
        column_history.record_column_result(
            target_date=date(2026, 9, 21), article=_ARTICLE,
            column=_column(), path=p)
        rows = column_history.load_history(path=p)["history"]
        _check("b1 同一日付は置換される（append しない）", len(rows) == 1,
               f"{len(rows)} 行")
        _check("b2 後の結果で上書きされる",
               rows and rows[0]["miibo_failed"] is False)


def test_broken_file_does_not_raise():
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "h.json"
        p.write_text("{ broken", encoding="utf-8")
        e = column_history.record_column_result(
            target_date=date(2026, 9, 21), article=_ARTICLE,
            column=_column(), path=p)
        _check("b3 壊れたログでも例外を投げない", e["miibo_called"] is True)


# ---------------------------------------------------------------------------
# (c)(d)(e) ★本番経路を通す — ここが本テストの核心
# ---------------------------------------------------------------------------

def _run_production(monkey_article, monkey_column, tmp_path: Path):
    """build_page_five_v2 を実際に呼び、書かれた履歴を返す.

    差し替えるのは外部 I/O（miibo / Anthropic / 記事選定）だけ。
    **record_column_result の呼び出しは差し替えない**。
    """
    from scripts import regen_front_page_v2 as v2
    from scripts.page5 import ai_kamiyama_selector as sel
    from scripts.page5 import article_summarizer as summ
    from scripts.page5 import column_history as ch

    orig = (sel.select_ai_kamiyama_article, summ.summarize_article,
            v2.page5_ai_kamiyama.write_column, ch.HISTORY_PATH)
    try:
        sel.select_ai_kamiyama_article = lambda **kw: monkey_article
        summ.summarize_article = lambda a: {"summary": "要約", "is_fallback": False}
        v2.page5_ai_kamiyama.write_column = lambda a, **kw: monkey_column
        ch.HISTORY_PATH = tmp_path
        v2.build_page_five_v2(date(2026, 9, 21))
    finally:
        (sel.select_ai_kamiyama_article, summ.summarize_article,
         v2.page5_ai_kamiyama.write_column, ch.HISTORY_PATH) = orig
    return column_history.load_history(path=tmp_path)["history"]


def test_production_path_records_success():
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "h.json"
        rows = _run_production(_ARTICLE, _column(), p)
        ok = len(rows) == 1 and rows[0]["miibo_called"] is True
        _check("c1 ★本番経路(build_page_five_v2)を通すと記録される", ok,
               f"{len(rows)} 行")
        _check("c2 論評した記事の URL が記録される",
               bool(rows) and rows[0]["article_url"] == _ARTICLE["url"])


def test_production_path_records_miibo_failure():
    """miibo が落ちても紙面は出る。その『静かな失敗』が残ること。"""
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "h.json"
        rows = _run_production(
            _ARTICLE, _column(failed=True, fallback=True, ms=0), p)
        ok = bool(rows) and rows[0]["miibo_failed"] is True
        _check("d1 ★本番経路で miibo 失敗が記録される", ok)
        _check("d2 点検関数が拾う",
               len(column_history.recent_failures(path=p)) == 1)


def test_production_path_records_placeholder():
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "h.json"
        rows = _run_production(None, None, p)
        ok = len(rows) == 1 and rows[0]["is_placeholder"] is True
        _check("e1 ★本番経路で休載が記録される", ok, f"{len(rows)} 行")


# ---------------------------------------------------------------------------
# (f) 回帰: 旧フィールドを serendipity 側に書き戻していないこと
# ---------------------------------------------------------------------------

def test_serendipity_no_longer_writes_column_fields():
    src = (Path(__file__).resolve().parents[2]
           / "scripts" / "selector" / "serendipity.py").read_text(encoding="utf-8")
    _check("f1 update_history_column_fields が消えている",
           "def update_history_column_fields(" not in src)
    body = src.split("def select_for_today")[-1] if "def select_for_today" in src else src
    _check("f2 履歴書き込みに ai_kamiyama_called を含めない",
           '"ai_kamiyama_called": False' not in body)


def main() -> int:
    print("C201: 第5面 一筆の観測ログ\n")
    print("(a) 記録の中身:")
    test_success_entry(); test_failure_entry(); test_placeholder_entry()
    print()
    print("(b) 冪等性・頑健性:")
    test_same_date_upserts(); test_broken_file_does_not_raise()
    print()
    print("(c)(d)(e) ★本番経路:")
    test_production_path_records_success()
    test_production_path_records_miibo_failure()
    test_production_path_records_placeholder()
    print()
    print("(f) 回帰:")
    test_serendipity_no_longer_writes_column_fields()
    print()
    print(f"=== {PASS} passed, {FAIL} failed ===")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
