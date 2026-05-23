"""Unit tests for page1_v3.next_week_preview (Phase 3, 2026-05-23).

Run::

    python3 -m tests.page1_v3.test_next_week_preview
"""

from __future__ import annotations

import sys
from datetime import date

from scripts.page1_v3.monthly_pivotal import WeekContext
from scripts.page1_v3.next_week_preview import build_next_week_preview

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


def _w2() -> WeekContext:
    return WeekContext(
        week_label="W2", theme="インド台頭",
        period=(date(2026, 5, 31), date(2026, 6, 6)),
        article={"title": "T", "url": "https://x/"},
        day_label="土", angle_key="response", angle_label_jp="応答",
    )


def test_next_week_present():
    out = build_next_week_preview(_w2())
    _check("a1 セクション class 含む",
           '<section class="next-week-preview">' in out)
    _check("a2 来週テーマが含まれる", "インド台頭" in out)
    _check("a3 期間が含まれる（5/31〜6/6）", "5/31" in out and "6/6" in out)
    _check("a4 7 行（日-土）含む", out.count('class="np-row"') == 7)
    _check("a5 「来週予告」バナー", '<h3 class="np-banner">来週予告</h3>' in out)
    _check("a6 placeholder クラス無し", "next-week-preview--pending" not in out)


def test_next_week_none_placeholder():
    out = build_next_week_preview(None)
    _check("b1 None → placeholder セクション",
           'class="next-week-preview next-week-preview--pending"' in out)
    _check("b2 'np-pending' テキスト含む", "np-pending" in out)
    _check("b3 「来週予告」バナーは保持", '<h3 class="np-banner">来週予告</h3>' in out)


def test_html_escape_in_theme():
    """テーマに HTML 特殊文字が混入しても escape される（防御的）."""
    week = WeekContext(
        week_label="WX", theme="<script>alert(1)</script>",
        period=(date(2026, 6, 7), date(2026, 6, 13)),
        article={"title": "T", "url": "https://x/"},
        day_label="日", angle_key="overview", angle_label_jp="全体像",
    )
    out = build_next_week_preview(week)
    _check("c1 テーマ内 <script> が escape",
           "&lt;script&gt;" in out and "<script>alert" not in out)


def main() -> int:
    print("page1_v3 — next_week_preview tests")
    print()
    print("(a) 来週ありの正常系:")
    test_next_week_present()
    print()
    print("(b) None placeholder:")
    test_next_week_none_placeholder()
    print()
    print("(c) HTML escape:")
    test_html_escape_in_theme()
    print()
    print(f"=== {PASS} passed, {FAIL} failed ===")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
