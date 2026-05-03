"""Unit tests for Page I HTML format change (Sprint 5, 2026-05-03).

Tests:
  a) _render_top_body / _render_secondary_body removed "原題：<em>...</em>"
     from byline (Q2 確定); kept the "全文：<a>" link.
  b) inject_page_one_css is idempotent and contains the expected selectors.
  c) build_page_one_v2 (with mocked sidebar) emits article-title-original /
     article-title-japanese for EN; omits article-title-japanese for JA.

Run::

    python3 -m tests.test_page_one_html_format
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
# (a) byline strips "原題：<em>...</em>"
# ---------------------------------------------------------------------------

def test_top_body_byline_format():
    """Sprint 6: byline は「出典：{label}」(plain text)、'原題：'/'全文：' はなし。"""
    article = {
        "title": "OpenAI Launches GPT-X",
        "description": "...",
        "desc_ja": "OpenAI が GPT-X を発表",
        "source_name": "BBC Business",
        "url": "https://test.test/article",
    }
    html = regen._render_top_body(article)
    no_genrei = "原題：" not in html and "<em>" not in html
    no_zenbun = "全文：" not in html
    has_shutten = "出典：" in html
    no_a_in_byline = '<a href="https://test.test/article"' not in html
    _check("a1 _render_top_body has no '原題：<em>' label", no_genrei,
           "byline must drop 原題 since h2 carries it now")
    _check("a2 _render_top_body has no '全文：<a>' link (Sprint 6)",
           no_zenbun and no_a_in_byline,
           "byline must drop 全文 link; URL link is on h2 now")
    _check("a3 _render_top_body has '出典：' label", has_shutten)


def test_secondary_body_byline_format():
    article = {
        "title": "Some Story",
        "description": "...",
        "desc_ja": "ある記事",
        "source_name": "The Economist",
        "url": "https://test.test/sec",
    }
    html = regen._render_secondary_body(article)
    no_genrei = "原題：" not in html and "<em>" not in html
    no_zenbun = "全文：" not in html
    has_shutten = "出典：" in html
    no_a_in_byline = '<a href="https://test.test/sec"' not in html
    _check("a4 _render_secondary_body has no '原題：<em>' label", no_genrei)
    _check("a5 _render_secondary_body has no '全文：<a>' link (Sprint 6)",
           no_zenbun and no_a_in_byline)
    _check("a6 _render_secondary_body has '出典：' label", has_shutten)


# ---------------------------------------------------------------------------
# (b) inject_page_one_css idempotent + has expected selectors
# ---------------------------------------------------------------------------

def test_inject_page_one_css_contains_selectors():
    has_original = ".article-title-original" in regen.PAGE_ONE_CSS
    has_ja = ".article-title-japanese" in regen.PAGE_ONE_CSS
    _check("b1 PAGE_ONE_CSS contains .article-title-original", has_original)
    _check("b2 PAGE_ONE_CSS contains .article-title-japanese", has_ja)


def test_inject_page_one_css_idempotent():
    template = "<html><head><style>body { color: red; }</style></head></html>"
    once = regen.inject_page_one_css(template)
    twice = regen.inject_page_one_css(once)
    once_count = once.count(regen.PAGE_ONE_CSS_MARKER)
    twice_count = twice.count(regen.PAGE_ONE_CSS_MARKER)
    _check("b3 first injection adds marker once", once_count == 1, f"count={once_count}")
    _check("b4 second injection is no-op (still 1)", twice_count == 1, f"count={twice_count}")


# ---------------------------------------------------------------------------
# (c) build_page_one_v2 — original-large + ja-small + ja-branching
# ---------------------------------------------------------------------------

def test_build_page_one_emits_new_format():
    """4 articles (1 EN top + 3 mixed) → check h2/h3 markup + ja-line presence."""
    # mock _build_sidebar to skip LLM
    original_sidebar = regen._build_sidebar
    regen._build_sidebar = lambda top: '<aside class="lead-sidebar">[mock]</aside>'
    try:
        articles = [
            {
                "title": "World Bank Pivots", "title_ja": "世銀がピボット",
                "description": "...", "desc_ja": "...",
                "source_name": "The Economist", "source_language": "en",
                "url": "https://e/1", "pub_date": "2026-05-03",
            },
            {
                "title": "ハンガリーの動向", "title_ja": "ハンガリーの動向",
                "description": "本文", "desc_ja": "本文",
                "source_name": "Foresight（新潮社）", "source_language": "ja",
                "url": "https://f/1", "pub_date": "2026-05-03",
            },
            {
                "title": "Reuters Story", "title_ja": "ロイターの記事",
                "description": "...", "desc_ja": "...",
                "source_name": "Reuters Business", "source_language": "en",
                "url": "https://r/1", "pub_date": "2026-05-03",
            },
            {
                "title": "BBC Story", "title_ja": "BBC の記事",
                "description": "...", "desc_ja": "...",
                "source_name": "BBC Business", "source_language": "en",
                "url": "https://b/1", "pub_date": "2026-05-03",
            },
        ]
        html = regen.build_page_one_v2(articles)
    finally:
        regen._build_sidebar = original_sidebar

    # Sprint 6: タイトルは <h2><a href>...</a></h2> 形式に変更
    # Top is EN → h2 has original wrapped in <a>, p.article-title-japanese has 世銀がピボット
    top_h2_orig = (
        '<h2 class="headline-xl article-title-original"><a href="https://e/1"' in html
        and '>World Bank Pivots</a></h2>' in html
    )
    top_jp = (
        '<p class="article-title-japanese">世銀がピボット</p>' in html
    )
    _check("c1 top EN article: h2><a> = original, jp line present", top_h2_orig and top_jp,
           f"h2_orig={top_h2_orig}, jp={top_jp}")

    # Secondary 1 is JA (Foresight) → no jp line, h3><a>title</a></h3>
    sec_ja_h3 = (
        '<h3 class="headline-l article-title-original"><a href="https://f/1"' in html
        and '>ハンガリーの動向</a></h3>' in html
    )
    # The JA article's title_ja line must NOT appear (would be duplicate)
    no_dup_ja = html.count("ハンガリーの動向") == 1
    _check("c2 JA secondary: h3 carries title; no separate jp line",
           sec_ja_h3 and no_dup_ja,
           f"h3_present={sec_ja_h3}, occurrences={html.count('ハンガリーの動向')}")

    # Secondary 2 (Reuters EN) → h3><a>title</a></h3> + jp line
    sec_en_h3 = (
        '<h3 class="headline-l article-title-original"><a href="https://r/1"' in html
        and '>Reuters Story</a></h3>' in html
    )
    sec_en_jp = '<p class="article-title-japanese">ロイターの記事</p>' in html
    _check("c3 EN secondary: h3><a> = original, jp line present",
           sec_en_h3 and sec_en_jp,
           f"h3={sec_en_h3}, jp={sec_en_jp}")

    # Genrei (原題：) label must be entirely gone
    _check("c4 no '原題：<em>' anywhere in built page", "原題：" not in html)


def main() -> int:
    print("Page I HTML format tests (Sprint 5, 2026-05-03)")
    print()
    print("(a) byline becomes plain '出典：' (Sprint 6):")
    test_top_body_byline_format()
    test_secondary_body_byline_format()
    print()
    print("(b) inject_page_one_css contents + idempotency:")
    test_inject_page_one_css_contains_selectors()
    test_inject_page_one_css_idempotent()
    print()
    print("(c) build_page_one_v2 emits new format:")
    test_build_page_one_emits_new_format()
    print()
    print(f"=== {PASS} passed, {FAIL} failed ===")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
