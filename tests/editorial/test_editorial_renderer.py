"""Unit tests for the editorial-footer rendering + injection (Sprint 4 Phase 3).

Tests:
  a) is_fallback=False → footer HTML emitted with label + body + signature
  b) is_fallback=True → empty string (no footer in archive)
  c) Empty body string → empty (treated as fallback)
  d) inject_editorial_css idempotency + rules present
  e) insert_editorial_footer places block before <footer class="colophon">
  f) insert_editorial_footer with empty footer_html is no-op
  g) insert_editorial_footer second call does not double-insert

Run::

    python3 -m tests.editorial.test_editorial_renderer
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
# (a) Normal render
# ---------------------------------------------------------------------------

def test_render_emits_footer():
    result = {
        "body": "本紙は今朝、二つの記事の対比から一つの問いを立てた。世界の中で何が共鳴し、何が遠ざかるのか、読者諸兄に静かに問う。",
        "is_fallback": False,
    }
    html = regen._render_editorial_footer(result)
    has_class = '<footer class="editorial-footer">' in html
    has_label = '<div class="label">編集後記</div>' in html
    has_body = '<div class="body">' in html
    has_signature = '<div class="signature">— Tribune 編集部</div>' in html
    has_text = result["body"] in html
    _check("a1 footer has class='editorial-footer'", has_class)
    _check("a2 footer has 編集後記 label", has_label)
    _check("a3 footer has body div", has_body)
    _check("a4 footer has Tribune signature", has_signature)
    _check("a5 body text rendered into footer", has_text)


# ---------------------------------------------------------------------------
# (b) Fallback render is empty
# ---------------------------------------------------------------------------

def test_fallback_emits_empty_string():
    result = {"body": "", "is_fallback": True}
    html = regen._render_editorial_footer(result)
    _check("b1 is_fallback=True → empty string",
           html == "", f"got len={len(html)}")


def test_none_or_missing_dict_emits_empty():
    _check("b2 None → empty",
           regen._render_editorial_footer(None) == "")
    _check("b3 empty dict → empty",
           regen._render_editorial_footer({}) == "")


# ---------------------------------------------------------------------------
# (c) Empty body treated as fallback
# ---------------------------------------------------------------------------

def test_empty_body_emits_empty_string():
    result = {"body": "", "is_fallback": False}
    _check("c1 is_fallback=False but empty body → empty",
           regen._render_editorial_footer(result) == "")


def test_whitespace_body_emits_empty_string():
    result = {"body": "   \n   ", "is_fallback": False}
    _check("c2 whitespace-only body → empty",
           regen._render_editorial_footer(result) == "")


# ---------------------------------------------------------------------------
# (d) CSS injection
# ---------------------------------------------------------------------------

def test_editorial_css_contents():
    css = regen.EDITORIAL_CSS
    _check("d1 EDITORIAL_CSS contains .editorial-footer rule",
           ".editorial-footer" in css)
    _check("d2 EDITORIAL_CSS contains .label rule",
           ".editorial-footer .label" in css)
    _check("d3 EDITORIAL_CSS contains .signature rule",
           ".editorial-footer .signature" in css)


def test_inject_editorial_css_idempotent():
    template = "<html><head><style>body{}</style></head><body></body></html>"
    once = regen.inject_editorial_css(template)
    twice = regen.inject_editorial_css(once)
    once_count = once.count(regen.EDITORIAL_CSS_MARKER)
    twice_count = twice.count(regen.EDITORIAL_CSS_MARKER)
    _check("d4 first injection adds marker once", once_count == 1)
    _check("d5 second injection is no-op (still 1)", twice_count == 1)


# ---------------------------------------------------------------------------
# (e) Insert position
# ---------------------------------------------------------------------------

def test_insert_before_colophon():
    html = """<html><body>
<section class="page page-six">PageVI</section>

<footer class="colophon">© Tribune</footer>
</body></html>"""
    footer = '<footer class="editorial-footer">EDITORIAL</footer>'
    out = regen.insert_editorial_footer(html, footer)
    edit_pos = out.find('<footer class="editorial-footer">')
    colo_pos = out.find('<footer class="colophon">')
    _check("e1 editorial footer inserted before colophon",
           edit_pos >= 0 and edit_pos < colo_pos,
           f"edit_pos={edit_pos}, colo_pos={colo_pos}")


def test_insert_no_colophon_falls_back_to_body_close():
    html = "<html><body><div>content</div></body></html>"
    footer = '<footer class="editorial-footer">EDITORIAL</footer>'
    out = regen.insert_editorial_footer(html, footer)
    edit_pos = out.find('<footer class="editorial-footer">')
    body_close = out.find("</body>")
    _check("e2 no colophon → inserted before </body>",
           edit_pos >= 0 and edit_pos < body_close)


# ---------------------------------------------------------------------------
# (f) Empty footer is no-op
# ---------------------------------------------------------------------------

def test_empty_footer_no_op():
    html = "<html><body><footer class=\"colophon\">©</footer></body></html>"
    out = regen.insert_editorial_footer(html, "")
    _check("f1 empty footer_html → no-op", out == html)


# ---------------------------------------------------------------------------
# (g) Idempotent against double insertion
# ---------------------------------------------------------------------------

def test_insert_idempotent():
    html = """<html><body>
<section>x</section>
<footer class="colophon">©</footer>
</body></html>"""
    footer = '<footer class="editorial-footer">EDITORIAL</footer>'
    once = regen.insert_editorial_footer(html, footer)
    twice = regen.insert_editorial_footer(once, footer)
    once_count = once.count('<footer class="editorial-footer">')
    twice_count = twice.count('<footer class="editorial-footer">')
    _check("g1 first insert adds editorial footer",
           once_count == 1, f"got {once_count}")
    _check("g2 second insert is no-op",
           twice_count == 1, f"got {twice_count}")


def main() -> int:
    print("Editorial renderer + injection tests (Sprint 4 Phase 3, 2026-05-03)")
    print()
    print("(a) Normal render:")
    test_render_emits_footer()
    print()
    print("(b) Fallback render is empty:")
    test_fallback_emits_empty_string()
    test_none_or_missing_dict_emits_empty()
    print()
    print("(c) Empty body treated as fallback:")
    test_empty_body_emits_empty_string()
    test_whitespace_body_emits_empty_string()
    print()
    print("(d) CSS injection:")
    test_editorial_css_contents()
    test_inject_editorial_css_idempotent()
    print()
    print("(e) Insert position:")
    test_insert_before_colophon()
    test_insert_no_colophon_falls_back_to_body_close()
    print()
    print("(f) Empty footer no-op:")
    test_empty_footer_no_op()
    print()
    print("(g) Idempotent:")
    test_insert_idempotent()
    print()
    print(f"=== {PASS} passed, {FAIL} failed ===")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
