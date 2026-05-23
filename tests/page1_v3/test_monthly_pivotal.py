"""Unit tests for page1_v3.monthly_pivotal (Phase 3, 2026-05-23).

Run::

    python3 -m tests.page1_v3.test_monthly_pivotal
"""

from __future__ import annotations

import json
import sys
import tempfile
from datetime import date
from pathlib import Path

from scripts.page1_v3 import monthly_pivotal as mp

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
# (a) angle_for_day: 曜日 → (label, key, jp)
# ---------------------------------------------------------------------------

def test_angle_for_each_weekday():
    expected = {
        date(2026, 5, 24): ("日", "overview", "全体像"),
        date(2026, 5, 25): ("月", "critical", "批判的"),
        date(2026, 5, 26): ("火", "practitioner", "実践者"),
        date(2026, 5, 27): ("水", "thinker", "思想家"),
        date(2026, 5, 28): ("木", "history", "歴史"),
        date(2026, 5, 29): ("金", "integration", "統合＋問い"),
        date(2026, 5, 30): ("土", "response", "応答"),
    }
    for d, exp in expected.items():
        got = mp.angle_for_day(d)
        _check(f"a1 {d.isoformat()} ({exp[0]}) → {exp[1]}", got == exp,
               f"got {got}")


# ---------------------------------------------------------------------------
# (b) load_monthly_pivotal: 実ファイル + 異常系
# ---------------------------------------------------------------------------

def test_load_real_pivotal_file():
    d = mp.load_monthly_pivotal()
    _check("b1 実 data/monthly_pivotal.json が読める", isinstance(d, dict) and "weeks" in d)
    _check("b2 W1-W4 が揃っている",
           set((d.get("weeks") or {}).keys()) >= {"W1", "W2", "W3", "W4"})


def test_load_missing_path_returns_empty():
    out = mp.load_monthly_pivotal(Path("/nonexistent/path/x.json"))
    _check("b3 ファイル無し → {}", out == {})


def test_load_corrupt_returns_empty():
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "corrupt.json"
        p.write_text("{not valid json", encoding="utf-8")
        out = mp.load_monthly_pivotal(p)
    _check("b4 壊れた JSON → {}", out == {})


# ---------------------------------------------------------------------------
# (c) find_week_for_date
# ---------------------------------------------------------------------------

def _build_monthly(period, theme="T", article=None) -> dict:
    return {
        "weeks": {
            "W1": {
                "theme": theme,
                "period": list(period),
                "article": article or {"title": "T1", "url": "https://x/1"},
            }
        }
    }


def test_find_week_basic():
    monthly = _build_monthly(("2026-05-24", "2026-05-30"))
    wc = mp.find_week_for_date(date(2026, 5, 24), monthly)
    _check("c1 期間先頭 → W1", wc is not None and wc.week_label == "W1")
    wc = mp.find_week_for_date(date(2026, 5, 30), monthly)
    _check("c2 期間末尾 → W1", wc is not None and wc.week_label == "W1")
    wc = mp.find_week_for_date(date(2026, 5, 27), monthly)
    _check("c3 期間内 → W1 + 水曜の angle",
           wc is not None and wc.week_label == "W1"
           and wc.angle_key == "thinker" and wc.angle_label_jp == "思想家")


def test_find_week_outside_period_returns_none():
    monthly = _build_monthly(("2026-05-24", "2026-05-30"))
    _check("c4 期間外 → None", mp.find_week_for_date(date(2026, 5, 23), monthly) is None)
    _check("c5 期間後 → None", mp.find_week_for_date(date(2026, 5, 31), monthly) is None)


def test_find_week_missing_article_fields_returns_none():
    """月次選定未了（title or url 欠落）→ None で caller が v2 fallback."""
    monthly = _build_monthly(("2026-05-24", "2026-05-30"),
                             article={"title": "", "url": "https://x/"})
    _check("c6 article.title 空 → None（v2 fallback）",
           mp.find_week_for_date(date(2026, 5, 24), monthly) is None)
    monthly = _build_monthly(("2026-05-24", "2026-05-30"),
                             article={"title": "T", "url": ""})
    _check("c7 article.url 空 → None", mp.find_week_for_date(date(2026, 5, 24), monthly) is None)


def test_find_week_real_pivotal_w1():
    """実ファイル：5/24 (日) → W1 'AIと暗黙知', angle=overview."""
    monthly = mp.load_monthly_pivotal()
    wc = mp.find_week_for_date(date(2026, 5, 24), monthly)
    _check(
        "c8 実 W1: 5/24 → AIと暗黙知 / overview",
        wc is not None and wc.theme == "AIと暗黙知"
        and wc.angle_key == "overview"
        and wc.article.get("title"),
        f"got {wc.theme if wc else None!r} / {wc.angle_key if wc else None}",
    )


# ---------------------------------------------------------------------------
# (d) find_next_week
# ---------------------------------------------------------------------------

def test_find_next_week_real():
    """実 W1 → W2 'インド台頭'."""
    monthly = mp.load_monthly_pivotal()
    w1 = mp.find_week_for_date(date(2026, 5, 24), monthly)
    next_w = mp.find_next_week(w1, monthly)
    _check("d1 W1 next → W2 'インド台頭'",
           next_w is not None and next_w.week_label == "W2"
           and next_w.theme == "インド台頭",
           f"got {next_w.theme if next_w else None}")


def test_find_next_week_returns_none_when_no_next():
    """W4 の翌週は未投入 → None."""
    monthly = mp.load_monthly_pivotal()
    w4 = mp.find_week_for_date(date(2026, 6, 14), monthly)
    next_w = mp.find_next_week(w4, monthly)
    _check("d2 W4 next → None（未投入）", next_w is None)


# ---------------------------------------------------------------------------
# (e) history_key: ユニーク性
# ---------------------------------------------------------------------------

def test_history_key_unique_per_period():
    monthly = mp.load_monthly_pivotal()
    w1 = mp.find_week_for_date(date(2026, 5, 24), monthly)
    w2 = mp.find_week_for_date(date(2026, 5, 31), monthly)
    _check("e1 history_key W1 ≠ W2", w1.history_key() != w2.history_key())
    _check("e2 history_key 形式: W1_2026-05-24",
           w1.history_key() == "W1_2026-05-24")


# ---------------------------------------------------------------------------
# (f) ANNOTATION_LABEL_BY_ANGLE
# ---------------------------------------------------------------------------

def test_annotation_labels_cover_all_angles():
    angles = {"overview", "critical", "practitioner", "thinker",
              "history", "integration", "response"}
    _check("f1 ANNOTATION_LABEL_BY_ANGLE が全 7 角度をカバー",
           set(mp.ANNOTATION_LABEL_BY_ANGLE.keys()) == angles)


def main() -> int:
    print("page1_v3 — monthly_pivotal tests")
    print()
    print("(a) angle_for_day:")
    test_angle_for_each_weekday()
    print()
    print("(b) load_monthly_pivotal:")
    test_load_real_pivotal_file()
    test_load_missing_path_returns_empty()
    test_load_corrupt_returns_empty()
    print()
    print("(c) find_week_for_date:")
    test_find_week_basic()
    test_find_week_outside_period_returns_none()
    test_find_week_missing_article_fields_returns_none()
    test_find_week_real_pivotal_w1()
    print()
    print("(d) find_next_week:")
    test_find_next_week_real()
    test_find_next_week_returns_none_when_no_next()
    print()
    print("(e) history_key:")
    test_history_key_unique_per_period()
    print()
    print("(f) ANNOTATION_LABEL_BY_ANGLE:")
    test_annotation_labels_cover_all_angles()
    print()
    print(f"=== {PASS} passed, {FAIL} failed ===")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
