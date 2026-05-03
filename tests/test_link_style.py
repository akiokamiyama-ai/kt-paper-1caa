"""Unit tests for the unified link style (Sprint 6, 2026-05-03).

Tests:
  a) inject_link_style_css contents (a / a:hover / a:visited rules)
  b) inject_link_style_css idempotency
  c) build_page_one_v2: top h2 + secondary h3 wrap title in <a>
  d) _render_page3_item: title wrapped in <a> when url present, plain otherwise
  e) _render_page_five: serendipity article-title wrapped in <a> when url present
  f) _render_leisure_column: byline source name wrapped in <a>, column-title plain

Run::

    python3 -m tests.test_link_style
"""

from __future__ import annotations

import sys

from scripts import regen_front_page_v2 as regen

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
# (a) LINK_STYLE_CSS contents
# ---------------------------------------------------------------------------

def test_link_style_css_contains_rules():
    css = regen.LINK_STYLE_CSS
    has_a_rule = "a {" in css
    has_color_inherit = "color: inherit" in css
    has_dotted_underline = "dotted" in css and "border-bottom" in css
    has_hover = "a:hover" in css
    has_visited = "a:visited" in css
    _check("a1 LINK_STYLE_CSS has 'a {' rule", has_a_rule)
    _check("a2 LINK_STYLE_CSS has color: inherit", has_color_inherit)
    _check("a3 LINK_STYLE_CSS has dotted border-bottom", has_dotted_underline)
    _check("a4 LINK_STYLE_CSS has a:hover rule", has_hover)
    _check("a5 LINK_STYLE_CSS has a:visited rule", has_visited)


# ---------------------------------------------------------------------------
# (b) idempotency
# ---------------------------------------------------------------------------

def test_inject_link_style_idempotent():
    template = "<html><head><style>body { color: red; }</style></head></html>"
    once = regen.inject_link_style_css(template)
    twice = regen.inject_link_style_css(once)
    once_count = once.count(regen.LINK_STYLE_CSS_MARKER)
    twice_count = twice.count(regen.LINK_STYLE_CSS_MARKER)
    _check("b1 first injection adds marker once", once_count == 1)
    _check("b2 second injection is no-op (still 1)", twice_count == 1)


def test_inject_link_style_no_style_tag():
    """If no </style>, inject creates a new <style> block before </head>."""
    template = "<html><head><title>x</title></head><body></body></html>"
    out = regen.inject_link_style_css(template)
    has_marker = regen.LINK_STYLE_CSS_MARKER in out
    has_new_style = "<style>" in out and "</style>" in out
    _check("b3 no </style> → injection wraps in new <style>",
           has_marker and has_new_style)


# ---------------------------------------------------------------------------
# (c) Page I: h2/h3 wrapped in <a>
# ---------------------------------------------------------------------------

def test_page_one_h2_h3_wrapped_in_a():
    original_sidebar = regen._build_sidebar
    regen._build_sidebar = lambda top: '<aside>[mock]</aside>'
    try:
        articles = [
            {
                "title": "Top Story", "title_ja": "トップ記事",
                "description": "...", "desc_ja": "...",
                "source_name": "The Economist", "source_language": "en",
                "url": "https://example.test/top", "pub_date": "2026-05-03",
            },
            {
                "title": "Sec1", "title_ja": "セク1",
                "description": ".", "desc_ja": ".",
                "source_name": "BBC Business", "source_language": "en",
                "url": "https://example.test/s1", "pub_date": "2026-05-03",
            },
            {
                "title": "Sec2", "title_ja": "セク2",
                "description": ".", "desc_ja": ".",
                "source_name": "Reuters Business", "source_language": "en",
                "url": "https://example.test/s2", "pub_date": "2026-05-03",
            },
            {
                "title": "Sec3", "title_ja": "セク3",
                "description": ".", "desc_ja": ".",
                "source_name": "BBC Business", "source_language": "en",
                "url": "https://example.test/s3", "pub_date": "2026-05-03",
            },
        ]
        html = regen.build_page_one_v2(articles)
    finally:
        regen._build_sidebar = original_sidebar
    top_a = (
        '<h2 class="headline-xl article-title-original">'
        '<a href="https://example.test/top"' in html
    )
    sec1_a = (
        '<h3 class="headline-l article-title-original">'
        '<a href="https://example.test/s1"' in html
    )
    sec2_a = (
        '<h3 class="headline-l article-title-original">'
        '<a href="https://example.test/s2"' in html
    )
    _check("c1 top h2 wraps title in <a href>", top_a)
    _check("c2 secondary 1 h3 wraps title in <a href>", sec1_a)
    _check("c3 secondary 2 h3 wraps title in <a href>", sec2_a)


# ---------------------------------------------------------------------------
# (d) Page III: _render_page3_item
# ---------------------------------------------------------------------------

def test_page_three_item_with_url_has_link():
    article = {
        "title": "Strategic Edge",
        "description": ".",
        "source_name": "War on the Rocks",
        "url": "https://example.test/page3-with-url",
        "pub_date": "2026-05-02",
    }
    html = regen._render_page3_item(article, "R1")
    has_link = (
        '<h5 class="headline-s">'
        '<a href="https://example.test/page3-with-url"' in html
    )
    _check("d1 page3 item with URL: h5 wraps title in <a>", has_link)


def test_page_three_item_without_url_plain_title():
    article = {
        "title": "No URL Story",
        "description": ".",
        "source_name": "Foresight",
        # url missing
        "pub_date": "2026-05-02",
    }
    html = regen._render_page3_item(article, "R1")
    no_link = '<a ' not in html
    plain_h5 = '<h5 class="headline-s">No URL Story</h5>' in html
    _check("d2 page3 item without URL: plain h5, no <a>", no_link and plain_h5)


# ---------------------------------------------------------------------------
# (e) Page V serendipity article-title
# ---------------------------------------------------------------------------

def test_page_five_serendipity_title_linked():
    serendipity = {
        "is_placeholder": False,
        "article": {
            "title": "Sauna Article",
            "description": "Sauna body excerpt...",
            "source_name": "AXIS",
            "url": "https://example.test/p5",
            "pub_date": "2026-05-01",
        },
    }
    column = {
        "column_title": "Sauna Column Title",
        "column_body": "Column body...",
    }
    html = regen._render_page_five(serendipity, column)
    title_linked = (
        '<h3 class="article-title">'
        '<a href="https://example.test/p5"' in html
    )
    column_title_plain = (
        '<h3 class="column-title">Sauna Column Title</h3>' in html
    )
    _check("e1 serendipity article-title wrapped in <a>", title_linked)
    _check("e2 AIかみやま column-title is plain (no <a>)", column_title_plain)


# ---------------------------------------------------------------------------
# (f) Page VI Leisure column byline source link
# ---------------------------------------------------------------------------

def test_leisure_column_byline_source_linked():
    result = {
        "column_title": "Trail Column Title",
        "column_body": "Column body...",
        "article": {
            "source_name": "The Trek",
            "url": "https://example.test/p6",
            "pub_date": "2026-05-02",
        },
    }
    html = regen._render_leisure_column(
        area_label="アウトドア", column_class="outdoor-column-v2", result=result,
    )
    # column-title should be plain (no <a>)
    column_title_plain = (
        '<h3 class="column-title">Trail Column Title</h3>' in html
    )
    # byline source name should be wrapped in <a>
    byline_linked = (
        '出典：<a href="https://example.test/p6"' in html
        and '>The Trek</a>' in html
    )
    _check("f1 leisure column-title is plain (no <a>)", column_title_plain)
    _check("f2 leisure byline source name wrapped in <a>", byline_linked)


def test_leisure_column_no_article_no_link():
    """If article is None, byline shows '本紙編集部' plain text."""
    result = {
        "column_title": "Title",
        "column_body": "Body",
        "article": None,
    }
    html = regen._render_leisure_column(
        area_label="アウトドア", column_class="outdoor-column-v2", result=result,
    )
    no_link = '<a ' not in html
    has_default = "本紙編集部" in html
    _check("f3 article=None: no <a>, byline=本紙編集部",
           no_link and has_default)


def main() -> int:
    print("Sprint 6 unified link style tests (2026-05-03)")
    print()
    print("(a) LINK_STYLE_CSS contents:")
    test_link_style_css_contains_rules()
    print()
    print("(b) inject_link_style_css idempotency:")
    test_inject_link_style_idempotent()
    test_inject_link_style_no_style_tag()
    print()
    print("(c) Page I h2/h3 wrap title in <a>:")
    test_page_one_h2_h3_wrapped_in_a()
    print()
    print("(d) Page III _render_page3_item:")
    test_page_three_item_with_url_has_link()
    test_page_three_item_without_url_plain_title()
    print()
    print("(e) Page V serendipity article-title:")
    test_page_five_serendipity_title_linked()
    print()
    print("(f) Page VI leisure column byline:")
    test_leisure_column_byline_source_linked()
    test_leisure_column_no_article_no_link()
    print()
    print(f"=== {PASS} passed, {FAIL} failed ===")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
