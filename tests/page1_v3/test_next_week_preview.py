"""Unit tests for page1_v3.next_week_preview (Phase 3, 2026-05-23).

C47 (Sprint 8, 2026-05-30): 旧 6 日間角度説明（np-row × 7）は削除。代わりに
主軸記事の 1 行紹介（np-pivotal）を出す。テストは新形式に追従。

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


def _w2_with_summary() -> WeekContext:
    """W2 リアルデータ寄りの fixture（インド台頭、主軸記事 + summary 入り）."""
    return WeekContext(
        week_label="W2", theme="インド台頭",
        period=(date(2026, 5, 31), date(2026, 6, 6)),
        article={
            "title": (
                "India is No Longer A Future Superpower. "
                "It Is Already Reshaping The Global Economy"
            ),
            "summary": (
                "インドを「将来の大国」と語ることはもはや時代錯誤になった。"
                "非同盟の伝統が「戦略的自律性」と「マルチアライメント」に進化し、"
                "米欧日豪と関係を深めながらエネルギー・防衛・通商で独自の利益を守る。"
            ),
            "url": "https://x/",
        },
        day_label="土", angle_key="response", angle_label_jp="応答",
    )


def _w2_title_only() -> WeekContext:
    """summary 欠落（旧データ互換）の最小 fixture."""
    return WeekContext(
        week_label="W2", theme="インド台頭",
        period=(date(2026, 5, 31), date(2026, 6, 6)),
        article={"title": "T", "url": "https://x/"},
        day_label="土", angle_key="response", angle_label_jp="応答",
    )


# ---------------------------------------------------------------------------
# (a) 正常系：summary 付き
# ---------------------------------------------------------------------------

def test_next_week_with_summary():
    out = build_next_week_preview(_w2_with_summary())
    _check("a1 セクション class 含む",
           '<section class="next-week-preview">' in out)
    _check("a2 来週テーマが含まれる", "インド台頭" in out)
    _check("a3 期間が含まれる（5/31〜6/6）", "5/31" in out and "6/6" in out)
    _check("a4 「来週予告」バナー", '<h3 class="np-banner">来週予告</h3>' in out)
    _check("a5 主軸記事タイトル含む（『India is No Longer A Future Superpower』）",
           "India is No Longer A Future Superpower" in out)
    _check("a6 タイトルを np-pivotal-title でハイライト",
           'class="np-pivotal-title">' in out)
    _check("a7 summary 抜粋が含まれる（戦略的自律性 / マルチアライメント）",
           "戦略的自律性" in out and "マルチアライメント" in out)
    _check("a8 末尾フレーズ「日本の経営者の眼差しで多角的に読み解きます。」",
           "日本の経営者の眼差しで多角的に読み解きます" in out)
    _check("a9 placeholder クラス無し", "next-week-preview--pending" not in out)
    _check("a10 旧 np-row / np-day / np-angle は削除済",
           'class="np-row"' not in out
           and 'class="np-day"' not in out
           and 'class="np-angle"' not in out)


# ---------------------------------------------------------------------------
# (b) summary 無し（後方互換）
# ---------------------------------------------------------------------------

def test_next_week_title_only():
    out = build_next_week_preview(_w2_title_only())
    _check("b1 summary 無しでも crash しない", "<section" in out)
    _check("b2 タイトルが含まれる", "『T』" in out)
    _check("b3 「日本の経営者の眼差しで」は末尾に残る",
           "日本の経営者の眼差しで多角的に読み解きます" in out)
    _check("b4 中段の summary 句は省略される（直接 末尾に繋がる）",
           "を主軸に、日本の経営者の眼差しで" in out)


# ---------------------------------------------------------------------------
# (c) None placeholder
# ---------------------------------------------------------------------------

def test_next_week_none_placeholder():
    out = build_next_week_preview(None)
    _check("c1 None → placeholder セクション",
           'class="next-week-preview next-week-preview--pending"' in out)
    _check("c2 'np-pending' テキスト含む", "np-pending" in out)
    _check("c3 「来週予告」バナーは保持", '<h3 class="np-banner">来週予告</h3>' in out)


# ---------------------------------------------------------------------------
# (d) HTML escape（防御的）
# ---------------------------------------------------------------------------

def test_html_escape_in_theme():
    """テーマに HTML 特殊文字が混入しても escape される."""
    week = WeekContext(
        week_label="WX", theme="<script>alert(1)</script>",
        period=(date(2026, 6, 7), date(2026, 6, 13)),
        article={"title": "T", "url": "https://x/"},
        day_label="日", angle_key="overview", angle_label_jp="全体像",
    )
    out = build_next_week_preview(week)
    _check("d1 テーマ内 <script> が escape",
           "&lt;script&gt;" in out and "<script>alert" not in out)


def test_html_escape_in_pivotal_title():
    """主軸記事タイトルに HTML 特殊文字が混入しても escape される."""
    week = WeekContext(
        week_label="WX", theme="X",
        period=(date(2026, 6, 7), date(2026, 6, 13)),
        article={"title": "<b>BadTitle</b>", "url": "https://x/"},
        day_label="日", angle_key="overview", angle_label_jp="全体像",
    )
    out = build_next_week_preview(week)
    _check("d2 タイトル内 <b> が escape",
           "&lt;b&gt;BadTitle&lt;/b&gt;" in out
           and "<b>BadTitle</b>" not in out)


# ---------------------------------------------------------------------------
# (e) 長文 title の truncate
# ---------------------------------------------------------------------------

def test_long_title_truncates_at_period():
    """副題付きタイトル『Main. Sub』は主節だけに丸まる."""
    week = WeekContext(
        week_label="WX", theme="X",
        period=(date(2026, 6, 7), date(2026, 6, 13)),
        article={
            "title": "India is No Longer A Future Superpower. It Is Already Reshaping The Global Economy",
            "url": "https://x/",
        },
        day_label="日", angle_key="overview", angle_label_jp="全体像",
    )
    out = build_next_week_preview(week)
    _check(
        "e1 副題は省略され『India is No Longer A Future Superpower』のみ",
        "India is No Longer A Future Superpower" in out
        and "It Is Already Reshaping" not in out,
    )


def test_long_summary_truncates_at_kuten():
    """summary が 120 字超なら句点で truncate."""
    # 120 字 boundary を確実に超えるため "ここから第一文の本体である。"(13字) × 10 =
    # 130 字を作り、その後に「出てはいけない」部分を足す。
    long_summary = (
        "ここから第一文の本体である。" * 10
        + "ここは出ないはずの後段。"
    )
    week = WeekContext(
        week_label="WX", theme="X",
        period=(date(2026, 6, 7), date(2026, 6, 13)),
        article={"title": "Short", "summary": long_summary, "url": "https://x/"},
        day_label="日", angle_key="overview", angle_label_jp="全体像",
    )
    out = build_next_week_preview(week)
    _check(
        "e2 長文 summary は句点で truncate（末尾の「ここは出ない…」は省略）",
        "ここから第一文の本体である。" in out
        and "ここは出ないはずの後段" not in out,
    )


def main() -> int:
    print("page1_v3 — next_week_preview tests (C47 redesign)")
    print()
    print("(a) 正常系（summary 付き）:")
    test_next_week_with_summary()
    print()
    print("(b) summary 無し（後方互換）:")
    test_next_week_title_only()
    print()
    print("(c) None placeholder:")
    test_next_week_none_placeholder()
    print()
    print("(d) HTML escape:")
    test_html_escape_in_theme()
    test_html_escape_in_pivotal_title()
    print()
    print("(e) 長文 title / summary の truncate:")
    test_long_title_truncates_at_period()
    test_long_summary_truncates_at_kuten()
    print()
    print(f"=== {PASS} passed, {FAIL} failed ===")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
