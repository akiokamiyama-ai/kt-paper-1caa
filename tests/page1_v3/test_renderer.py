"""Unit tests for page1_v3.renderer (Phase 3, 2026-05-23).

Run::

    python3 -m tests.page1_v3.test_renderer
"""

from __future__ import annotations

import sys
from datetime import date

from scripts.page1_v3 import renderer as r
from scripts.page1_v3.essay_generator import EssayResult
from scripts.page1_v3.monthly_pivotal import WeekContext
from scripts.page1_v3.saturday_responder import SaturdayResult

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


def _wc(day_label: str = "日", angle_key: str = "overview",
        angle_label_jp: str = "全体像") -> WeekContext:
    return WeekContext(
        week_label="W1", theme="AIと暗黙知",
        period=(date(2026, 5, 24), date(2026, 5, 30)),
        article={
            "title": "The Death of Tacit Knowledge",
            "source": "Past Tense Tomorrow",
            "author": "Mike Turner",
            "published": "2026-04-13",
            "url": "https://example.test/article",
        },
        day_label=day_label, angle_key=angle_key, angle_label_jp=angle_label_jp,
    )


def _essay(is_fallback: bool = False) -> EssayResult:
    return EssayResult(
        angle_label="日曜 - 全体像",
        daily_question="人間にしか分からない『勘所』はどこへ行くのか",
        essay_title="ポランニーから読み解く AI と暗黙知",
        body="第一段落の本文。\n\n第二段落。\n\n第三段落。",
        annotation_label="主要キーワード",
        annotation_body="暗黙知・形式知・SECIモデル。",
        quote_excerpt="主軸記事からの引用 300-500 字相当のテキスト。",
        cost_usd=0.05, is_fallback=is_fallback,
    )


def _sat(is_fallback: bool = False, with_digest: bool = True,
         with_daily_q: bool = True) -> SaturdayResult:
    return SaturdayResult(
        angle_label="土曜 - 応答",
        daily_question="今週、ともに聞きました" if with_daily_q else "",
        response_title="一週間の聞き取り",
        comments_digest=(
            "神山さんは月曜に...と書きました。\n\n水曜には..."
            if with_digest else ""
        ),
        response_body="AIかみやま応答本文 段落 1。\n\n段落 2。",
        digest_cost_usd=0.003, is_fallback=is_fallback,
    )


# ---------------------------------------------------------------------------
# (a) 日-金論考の正常レンダリング
# ---------------------------------------------------------------------------

def test_essay_render_basic():
    html = r.render_page_one_v3(date(2026, 5, 24), _wc(), _essay())
    _check("a1 page-one-v3 セクション存在",
           '<section class="page page-one-v3"' in html)
    _check("a2 data-date 属性付与", 'data-date="2026-05-24"' in html)
    _check("a3 theme banner にテーマ", "AIと暗黙知" in html)
    _check("a4 階層 1: angle_label", "日曜 - 全体像" in html)
    _check("a5 階層 2: daily_question",
           "人間にしか分からない『勘所』はどこへ行くのか" in html)
    _check("a6 階層 3: essay_title",
           "ポランニーから読み解く AI と暗黙知" in html)
    _check("a7 本文段落 3 つ → <p> 3 つ",
           html.count("<p") >= 3)
    _check("a8 lede クラス (dropcap)", 'class="lede"' in html)
    _check("a9 用語解説ラベル", "主要キーワード" in html)
    _check("a10 用語解説本文", "暗黙知・形式知・SECIモデル。" in html)
    _check("a11 主軸記事ボックス",
           '<aside class="pivotal-article">' in html
           and "The Death of Tacit Knowledge" in html)
    _check("a12 主軸記事リンク",
           'href="https://example.test/article"' in html
           and 'target="_blank"' in html)
    _check("a13 主軸記事メタ（source · author · published）",
           "Past Tense Tomorrow" in html and "Mike Turner" in html
           and "2026-04-13" in html)
    _check("a14 引用ブロック",
           '<blockquote class="pivotal-quote">' in html)
    _check("a15 fallback クラス無し", "essay--fallback" not in html)
    _check("a16 来週予告無し（日-金）",
           '<section class="next-week-preview"' not in html
           and 'class="next-week-preview"' not in html)


def test_essay_render_fallback_class():
    html = r.render_page_one_v3(date(2026, 5, 25), _wc("月", "critical", "批判的"),
                                 _essay(is_fallback=True))
    _check("b1 fallback essay → essay--fallback クラス", "essay--fallback" in html)
    _check("b2 fallback でも 3 階層タイトル要素は残る",
           "essay-tier1" in html and "essay-tier2" in html and "essay-tier3" in html)


# ---------------------------------------------------------------------------
# (c) HTML escape
# ---------------------------------------------------------------------------

def test_escape_in_body_and_title():
    essay = _essay()
    essay.body = "<script>alert(1)</script>\n\n通常段落"
    essay.essay_title = "Tom & Jerry <fake>"
    html = r.render_page_one_v3(date(2026, 5, 24), _wc(), essay)
    _check("c1 body の <script> が escape",
           "&lt;script&gt;" in html and "<script>alert" not in html)
    _check("c2 title の & が escape",
           "Tom &amp; Jerry" in html)


# ---------------------------------------------------------------------------
# (d) 土曜応答のレンダリング
# ---------------------------------------------------------------------------

def test_saturday_render_full():
    wc = _wc("土", "response", "応答")
    html = r.render_page_one_v3(date(2026, 5, 30), wc, _sat(),
                                 next_week_preview_html='<section class="next-week-preview"><h3 class="np-banner">来週予告</h3>来週ね</section>')
    _check("d1 saturday-response クラス", "saturday-response" in html)
    _check("d2 階層 1 '土曜 - 応答'", "土曜 - 応答" in html)
    _check("d3 階層 2 daily_question（任意の問い）",
           "今週、ともに聞きました" in html)
    _check("d4 階層 3 response_title",
           "一週間の聞き取り" in html)
    _check("d5 comments-digest セクション",
           '<aside class="comments-digest">' in html
           and "神山さんは月曜に" in html)
    _check("d6 response-body クラスの本文",
           'class="essay-body response-body"' in html)
    _check("d7 AIかみやま byline",
           '<p class="ai-byline">— AIかみやま</p>' in html)
    _check("d8 主軸記事ボックスは引用無し（土曜）",
           '<aside class="pivotal-article">' in html
           and '<blockquote class="pivotal-quote">' not in html)
    _check("d9 来週予告セクション組み込み",
           '<section class="next-week-preview">' in html
           and "来週ね" in html)


def test_saturday_without_daily_question_skips_tier2():
    html = r.render_page_one_v3(date(2026, 5, 30), _wc("土", "response", "応答"),
                                 _sat(with_daily_q=False))
    _check("e1 daily_question 空 → 階層 2 ヘッダ無し",
           'class="essay-tier2 daily-question"' not in html)
    _check("e2 階層 1 と 3 は残る",
           "essay-tier1" in html and "essay-tier3" in html)


def test_saturday_empty_digest():
    """コメント 0 件 → comments_digest 空 → digest セクション省略."""
    html = r.render_page_one_v3(date(2026, 5, 30), _wc("土", "response", "応答"),
                                 _sat(with_digest=False))
    _check("f1 digest 空 → comments-digest セクション無し",
           '<aside class="comments-digest">' not in html)


# ---------------------------------------------------------------------------
# (g) CSS inject helper
# ---------------------------------------------------------------------------

def test_inject_css_into_existing_style():
    template = "<html><head><style>body{}</style></head><body></body></html>"
    out = r.inject_page_one_v3_css(template)
    _check("g1 既存 </style> 直前に inject",
           ".page-one-v3" in out and out.count("</style>") == 1)


def test_inject_css_when_no_style():
    template = "<html><head><title>x</title></head><body></body></html>"
    out = r.inject_page_one_v3_css(template)
    _check("g2 </style> 無し → <style> 新設して </head> 直前に",
           "<style>" in out and ".page-one-v3" in out
           and out.index("<style>") < out.index("</head>"))


def test_inject_css_no_head_no_change():
    template = "<no head no nothing>"
    out = r.inject_page_one_v3_css(template)
    _check("g3 </head> も無し → 元のまま返す", out == template)


# ---------------------------------------------------------------------------
# (h) 段落分割
# ---------------------------------------------------------------------------

def test_paragraphs_split_by_double_newline():
    out = r._paragraphs_html("段落1\n\n段落2\n\n段落3")
    _check("h1 \\n\\n で 3 段落", out.count("<p") == 3)
    _check("h2 先頭段落に lede", out.startswith('<p class="lede">'))


def test_paragraphs_single_newline_becomes_br():
    out = r._paragraphs_html("行1\n行2")
    _check("h3 単一改行 → <br>", "行1<br>行2" in out)


def test_paragraphs_empty():
    _check("h4 空文字 → 空文字", r._paragraphs_html("") == "")


# ---------------------------------------------------------------------------
# (i) C52 safety net — マークダウン **bold** → <strong>
# ---------------------------------------------------------------------------

def test_markdown_bold_converted_to_strong():
    out = r._paragraphs_html("**製造業のリスク**\n\n本文段落")
    _check(
        "i1 **bold** → <strong>bold</strong>",
        "<strong>製造業のリスク</strong>" in out
        and "**製造業" not in out,
        f"got {out!r}",
    )


def test_markdown_bold_inside_paragraph():
    out = r._paragraphs_html("文章中に **強調語** がある段落")
    _check(
        "i2 段落の途中にある **bold** も変換",
        "文章中に <strong>強調語</strong> がある段落" in out,
        f"got {out!r}",
    )


def test_markdown_bold_multiple_occurrences():
    out = r._paragraphs_html("**前** と **後** がある")
    _check(
        "i3 1 段落内に複数の **bold** があっても全て変換",
        out.count("<strong>") == 2 and "**" not in out,
        f"got {out!r}",
    )


def test_no_markdown_bold_no_change():
    out = r._paragraphs_html("普通の段落、強調なし")
    _check(
        "i4 マークダウンなしの段落は <strong> が入らない",
        "<strong>" not in out and "普通の段落" in out,
    )


def test_lone_asterisks_not_misinterpreted():
    """単独 ** や 3 つ以上の連続 * は変換対象外（誤マッチ防止）."""
    out = r._paragraphs_html("単独 ** が一つ")
    _check(
        "i5 単独の ** は変換対象外",
        "<strong>" not in out,
        f"got {out!r}",
    )


def main() -> int:
    print("page1_v3 — renderer tests")
    print()
    print("(a) essay render 正常系:")
    test_essay_render_basic()
    print()
    print("(b) essay fallback:")
    test_essay_render_fallback_class()
    print()
    print("(c) HTML escape:")
    test_escape_in_body_and_title()
    print()
    print("(d) saturday render 正常系:")
    test_saturday_render_full()
    print()
    print("(e) saturday daily_question 任意:")
    test_saturday_without_daily_question_skips_tier2()
    print()
    print("(f) saturday digest 空:")
    test_saturday_empty_digest()
    print()
    print("(g) CSS inject helper:")
    test_inject_css_into_existing_style()
    test_inject_css_when_no_style()
    test_inject_css_no_head_no_change()
    print()
    print("(i) C52 safety net (markdown **bold** → <strong>):")
    test_markdown_bold_converted_to_strong()
    test_markdown_bold_inside_paragraph()
    test_markdown_bold_multiple_occurrences()
    test_no_markdown_bold_no_change()
    test_lone_asterisks_not_misinterpreted()
    print()
    print("(h) paragraph 分割:")
    test_paragraphs_split_by_double_newline()
    test_paragraphs_single_newline_becomes_br()
    test_paragraphs_empty()
    print()
    print(f"=== {PASS} passed, {FAIL} failed ===")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
