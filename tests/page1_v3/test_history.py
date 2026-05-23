"""Unit tests for page1_v3.history (Phase 3, 2026-05-23).

Run::

    python3 -m tests.page1_v3.test_history
"""

from __future__ import annotations

import json
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from scripts.page1_v3 import history as h
from scripts.page1_v3.monthly_pivotal import WeekContext

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


# Test 用の最小 dataclass（実 EssayResult を import すると循環するため）
@dataclass
class _FakeEssay:
    angle_label: str = ""
    daily_question: str = ""
    essay_title: str = ""
    body: str = ""
    cost_usd: float = 0.0
    is_fallback: bool = False


def _wc(day_label: str = "日", angle_key: str = "overview",
        angle_label_jp: str = "全体像") -> WeekContext:
    return WeekContext(
        week_label="W1", theme="AIと暗黙知",
        period=(date(2026, 5, 24), date(2026, 5, 30)),
        article={"title": "T", "url": "https://x/"},
        day_label=day_label, angle_key=angle_key, angle_label_jp=angle_label_jp,
    )


# ---------------------------------------------------------------------------
# (a) save + load roundtrip
# ---------------------------------------------------------------------------

def test_save_then_load():
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "h.json"
        wc = _wc()
        essay = _FakeEssay(angle_label="日曜 - 全体像", essay_title="X", body="本文")
        h.save_essay(wc, date(2026, 5, 24), essay, history_path=path)
        out = h.load_week_essays(wc, history_path=path)
    _check("a1 1 件保存 → 1 件読める", len(out) == 1, f"got {len(out)}")
    _check("a2 essay 内容が保持", out[0]["essay"]["body"] == "本文")
    _check("a3 メタ（angle_key 等）も保持", out[0]["angle_key"] == "overview")


# ---------------------------------------------------------------------------
# (b) 同日上書き（再ラン耐性）
# ---------------------------------------------------------------------------

def test_same_date_overwrite():
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "h.json"
        wc = _wc()
        h.save_essay(wc, date(2026, 5, 24), _FakeEssay(body="v1"), history_path=path)
        h.save_essay(wc, date(2026, 5, 24), _FakeEssay(body="v2"), history_path=path)
        out = h.load_week_essays(wc, history_path=path)
    _check("b1 同日再保存 → 1 件のまま（上書き）", len(out) == 1)
    _check("b2 最新内容に置換", out[0]["essay"]["body"] == "v2")


# ---------------------------------------------------------------------------
# (c) 日付順ソート
# ---------------------------------------------------------------------------

def test_entries_sorted_by_date():
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "h.json"
        wc = _wc()
        # 順不同で保存
        h.save_essay(wc, date(2026, 5, 27), _FakeEssay(body="水"), history_path=path)
        h.save_essay(wc, date(2026, 5, 24), _FakeEssay(body="日"), history_path=path)
        h.save_essay(wc, date(2026, 5, 25), _FakeEssay(body="月"), history_path=path)
        out = h.load_week_essays(wc, history_path=path)
    _check("c1 3 件、日付昇順", [e["date"] for e in out] == ["2026-05-24", "2026-05-25", "2026-05-27"])


# ---------------------------------------------------------------------------
# (d) 別週との独立性
# ---------------------------------------------------------------------------

def test_different_week_isolated():
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "h.json"
        w1 = _wc()
        w2 = WeekContext(
            week_label="W2", theme="インド台頭",
            period=(date(2026, 5, 31), date(2026, 6, 6)),
            article={"title": "T2", "url": "https://x/2"},
            day_label="日", angle_key="overview", angle_label_jp="全体像",
        )
        h.save_essay(w1, date(2026, 5, 24), _FakeEssay(body="W1"), history_path=path)
        h.save_essay(w2, date(2026, 5, 31), _FakeEssay(body="W2"), history_path=path)
        w1_essays = h.load_week_essays(w1, history_path=path)
        w2_essays = h.load_week_essays(w2, history_path=path)
    _check("d1 W1 のみ取れる（W2 が混入しない）",
           len(w1_essays) == 1 and w1_essays[0]["essay"]["body"] == "W1")
    _check("d2 W2 も独立に取れる",
           len(w2_essays) == 1 and w2_essays[0]["essay"]["body"] == "W2")


# ---------------------------------------------------------------------------
# (e) ファイル未作成 → 空リスト
# ---------------------------------------------------------------------------

def test_load_missing_returns_empty():
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "missing.json"
        out = h.load_week_essays(_wc(), history_path=path)
    _check("e1 未保存 → []", out == [])


# ---------------------------------------------------------------------------
# (f) atomic write（破損 JSON は graceful）
# ---------------------------------------------------------------------------

def test_corrupt_history_treated_as_empty():
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "h.json"
        path.write_text("{not valid", encoding="utf-8")
        out = h.load_week_essays(_wc(), history_path=path)
    _check("f1 破損 JSON → []（caller は新規扱い）", out == [])


def main() -> int:
    print("page1_v3 — history tests")
    print()
    print("(a) save/load roundtrip:")
    test_save_then_load()
    print()
    print("(b) 同日上書き:")
    test_same_date_overwrite()
    print()
    print("(c) 日付順ソート:")
    test_entries_sorted_by_date()
    print()
    print("(d) 別週独立:")
    test_different_week_isolated()
    print()
    print("(e) ファイル未作成:")
    test_load_missing_returns_empty()
    print()
    print("(f) 破損 JSON:")
    test_corrupt_history_treated_as_empty()
    print()
    print(f"=== {PASS} passed, {FAIL} failed ===")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
