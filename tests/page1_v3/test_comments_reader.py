"""Unit tests for page1_v3.comments_reader (Phase 3, 2026-05-23).

Run::

    python3 -m tests.page1_v3.test_comments_reader
"""

from __future__ import annotations

import sys
import tempfile
from datetime import date
from pathlib import Path

from scripts.page1_v3 import comments_reader as cr
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


def _w1_context() -> WeekContext:
    return WeekContext(
        week_label="W1",
        theme="AIと暗黙知",
        period=(date(2026, 5, 24), date(2026, 5, 30)),
        article={"title": "T", "url": "https://x/"},
        day_label="日",
        angle_key="overview",
        angle_label_jp="全体像",
    )


# ---------------------------------------------------------------------------
# (a) ファイル無し → 空リスト
# ---------------------------------------------------------------------------

def test_no_comments_returns_empty():
    with tempfile.TemporaryDirectory() as td:
        out = cr.load_week_comments(_w1_context(), comments_dir=Path(td))
    _check("a1 空ディレクトリ → []", out == [])


# ---------------------------------------------------------------------------
# (b) 一部の日だけ存在
# ---------------------------------------------------------------------------

def test_some_days_present():
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        (base / "2026-05-24.md").write_text("日曜のコメント本文", encoding="utf-8")
        (base / "2026-05-27.md").write_text("水曜のコメント", encoding="utf-8")
        out = cr.load_week_comments(_w1_context(), comments_dir=base)
    _check("b1 2 日分だけ存在 → 2 entry", len(out) == 2, f"got {len(out)}")
    _check("b2 日付順", [c.target_date for c in out] == [date(2026, 5, 24), date(2026, 5, 27)])
    _check("b3 5/24 → 日曜・全体像",
           out[0].day_label == "日" and out[0].angle_label_jp == "全体像")
    _check("b4 5/27 → 水曜・思想家",
           out[1].day_label == "水" and out[1].angle_label_jp == "思想家")
    _check("b5 body は md 全文（strip のみ）",
           out[0].body == "日曜のコメント本文")


# ---------------------------------------------------------------------------
# (c) 空ファイルは entry に含めない
# ---------------------------------------------------------------------------

def test_empty_files_excluded():
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        (base / "2026-05-24.md").write_text("", encoding="utf-8")
        (base / "2026-05-25.md").write_text("   \n   ", encoding="utf-8")
        (base / "2026-05-26.md").write_text("非空コメント", encoding="utf-8")
        out = cr.load_week_comments(_w1_context(), comments_dir=base)
    _check("c1 空ファイル / 空白のみ → 除外", len(out) == 1, f"got {len(out)}")
    _check("c2 残った 1 件は 5/26", out[0].target_date == date(2026, 5, 26))


# ---------------------------------------------------------------------------
# (d) include_saturday デフォルト False（土曜除外）
# ---------------------------------------------------------------------------

def test_saturday_excluded_by_default():
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        for d in ["2026-05-24", "2026-05-25", "2026-05-26", "2026-05-27",
                  "2026-05-28", "2026-05-29", "2026-05-30"]:
            (base / f"{d}.md").write_text(f"comment {d}", encoding="utf-8")
        out_default = cr.load_week_comments(_w1_context(), comments_dir=base)
        out_with_sat = cr.load_week_comments(_w1_context(), comments_dir=base,
                                             include_saturday=True)
    _check("d1 デフォルト 6 日分（日-金、土曜除外）", len(out_default) == 6, f"got {len(out_default)}")
    _check("d2 include_saturday=True で 7 日分", len(out_with_sat) == 7, f"got {len(out_with_sat)}")
    _check("d3 デフォルトに土曜が含まれない",
           all(c.target_date != date(2026, 5, 30) for c in out_default))


# ---------------------------------------------------------------------------
# (e) is_empty プロパティ
# ---------------------------------------------------------------------------

def test_daily_comment_is_empty_property():
    c = cr.DailyComment(target_date=date(2026, 5, 24), day_label="日",
                        angle_label_jp="全体像", body="x")
    _check("e1 body 有り → is_empty=False", c.is_empty is False)
    c2 = cr.DailyComment(target_date=date(2026, 5, 24), day_label="日",
                         angle_label_jp="全体像", body="   ")
    _check("e2 空白のみ → is_empty=True", c2.is_empty is True)


def main() -> int:
    print("page1_v3 — comments_reader tests")
    print()
    print("(a) ファイル無し:")
    test_no_comments_returns_empty()
    print()
    print("(b) 一部の日だけ存在:")
    test_some_days_present()
    print()
    print("(c) 空ファイル除外:")
    test_empty_files_excluded()
    print()
    print("(d) include_saturday:")
    test_saturday_excluded_by_default()
    print()
    print("(e) is_empty プロパティ:")
    test_daily_comment_is_empty_property()
    print()
    print(f"=== {PASS} passed, {FAIL} failed ===")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
