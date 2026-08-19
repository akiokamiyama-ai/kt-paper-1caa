"""単日 Page I 再生成のための swap 冪等化 (C174, 2026-08-19).

背景
----
2026-08-19 の Page I が essay の parse 失敗で休載した（C172 で救済を実装）。
救済入りのコードで論考を作り直したかったが、**Page I だけを再生成する手段が
無かった**:

  * ``_run_production`` は必ず v2 main を先に呼ぶ → 全 6 面が再生成され、
    記事選定が当日の feed で変わる。さらに concept / cooking / page5 の
    各 history は append 実装なので同じ日付が二重記録される
  * ``_swap_page_one`` は v2 の ``<section class="page page-one">`` 完全一致
    しか見ておらず、既に v3 化された archive には no-op
  * ``inject_page_one_v3_css`` は呼ばれるたびに CSS を足すので、再 swap で
    CSS ブロックが丸ごと二重になる

Tests:
  a) v2 / v3 どちらの page-one でも swap できる
  b) swap が他面を壊さない
  c) CSS 注入が冪等
  d) --page-one-only フラグの配線
  e) 実データ（archive/2026-08-19.html）での回帰

Run::

    python3 -m tests.page1_v3.test_page_one_only_swap
"""

from __future__ import annotations

import sys
from pathlib import Path

from scripts.page1_v3.renderer import (
    PAGE_ONE_V3_CSS,
    PAGE_ONE_V3_CSS_MARKER,
    inject_page_one_v3_css,
)
from scripts.regen_front_page_v3 import (
    PAGE_ONE_SECTION_RE,
    _build_parser,
    _swap_page_one,
)

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


_NEW = '<section class="page page-one-v3" data-date="X">NEW</section>'


def _doc(page_one_tag: str) -> str:
    return (
        "<html><head><style>body{}</style></head><body>"
        f"{page_one_tag}OLD</section>"
        '<section class="page page-two">P2</section>'
        '<section class="page page-six">P6</section>'
        "</body></html>"
    )


# ---------------------------------------------------------------------------
# (a) v2 / v3 どちらでも swap できる
# ---------------------------------------------------------------------------

def test_swap_v2_marker():
    out = _swap_page_one(_doc('<section class="page page-one">'), _NEW)
    _check("a1 v2 の page-one を swap できる（従来動作）",
           "NEW" in out and "OLD" not in out)


def test_swap_v3_marker_with_attrs():
    tag = '<section class="page page-one-v3" data-date="2026-08-19">'
    out = _swap_page_one(_doc(tag), _NEW)
    _check("a2 v3 の page-one を swap できる（C174 で追加）",
           "NEW" in out and "OLD" not in out)


def test_regex_matches_both():
    _check("a3 正規表現が v2 に当たる",
           PAGE_ONE_SECTION_RE.search('<section class="page page-one">') is not None)
    _check("a4 正規表現が v3 + 属性に当たる",
           PAGE_ONE_SECTION_RE.search(
               '<section class="page page-one-v3" data-date="2026-08-19">'
           ) is not None)
    _check("a5 他面には当たらない",
           PAGE_ONE_SECTION_RE.search('<section class="page page-two">') is None)


def test_missing_section_raises():
    try:
        _swap_page_one("<html><body>no sections</body></html>", _NEW)
    except RuntimeError:
        _check("a6 page-one が無ければ RuntimeError", True)
        return
    _check("a6 page-one が無ければ RuntimeError", False, "例外が出なかった")


# ---------------------------------------------------------------------------
# (b) 他面を壊さない
# ---------------------------------------------------------------------------

def test_other_pages_survive():
    tag = '<section class="page page-one-v3" data-date="2026-08-19">'
    out = _swap_page_one(_doc(tag), _NEW)
    _check("b1 2 面が残る", "P2" in out)
    _check("b2 6 面が残る", "P6" in out)
    _check("b3 section 数が変わらない",
           out.count('<section class="page ') == 3,
           str(out.count('<section class="page ')))


def test_swap_is_repeatable():
    tag = '<section class="page page-one-v3" data-date="2026-08-19">'
    once = _swap_page_one(_doc(tag), _NEW)
    twice = _swap_page_one(once, _NEW)
    _check("b4 2 回 swap しても増殖しない（再ラン耐性）", once == twice)


# ---------------------------------------------------------------------------
# (c) CSS 注入の冪等性
# ---------------------------------------------------------------------------

def test_css_injection_idempotent():
    h = "<html><head><style>body{}</style></head><body></body></html>"
    a = inject_page_one_v3_css(h)
    b = inject_page_one_v3_css(a)
    _check("c1 CSS 注入は冪等", a == b)
    _check("c2 マーカーは 1 回だけ", b.count(PAGE_ONE_V3_CSS_MARKER) == 1,
           str(b.count(PAGE_ONE_V3_CSS_MARKER)))


def test_css_marker_is_in_css():
    _check("c3 マーカーが実際に CSS 内にある（定数のズレ防止）",
           PAGE_ONE_V3_CSS_MARKER in PAGE_ONE_V3_CSS)


def test_css_injected_when_absent():
    h = "<html><head><style>body{}</style></head><body></body></html>"
    _check("c4 未注入なら注入する",
           PAGE_ONE_V3_CSS_MARKER in inject_page_one_v3_css(h))


# ---------------------------------------------------------------------------
# (d) --page-one-only の配線
# ---------------------------------------------------------------------------

def test_flag_parsed():
    known, _ = _build_parser().parse_known_args(
        ["--date", "2026-08-19", "--page-one-only"]
    )
    _check("d1 --page-one-only が parse される", known.page_one_only is True)
    _check("d2 既定は False",
           _build_parser().parse_known_args(["--date", "2026-08-19"])[0]
           .page_one_only is False)


def test_page_one_only_does_not_call_v2():
    """v2 を呼ばないことをソース上で担保（呼ぶと全面再生成になる）."""
    import inspect

    from scripts import regen_front_page_v3 as v3

    src = inspect.getsource(v3._run_page_one_only)
    _check("d3 _run_page_one_only は v2 main を呼ばない",
           "regen_front_page_v2" not in src and "v2_argv" not in src)
    _check("d4 _try_v3_swap は呼ぶ", "_try_v3_swap" in src)


# ---------------------------------------------------------------------------
# (e) 実データ回帰
# ---------------------------------------------------------------------------

def test_real_archive():
    root = Path(__file__).resolve().parents[2]
    target = root / "archive" / "2026-08-19.html"
    if not target.exists():
        _check("e1 archive/2026-08-19.html が存在", False, str(target))
        return
    html = target.read_text(encoding="utf-8")
    m = PAGE_ONE_SECTION_RE.search(html)
    _check("e1 実 archive の page-one に当たる", m is not None,
           m.group(0) if m else "")
    out = _swap_page_one(html, _NEW)
    _check("e2 6 面すべて残る",
           out.count('<section class="page ') == 6,
           str(out.count('<section class="page ')))
    for page in ("Page II", "Page III", "Page IV", "Page V", "Page VI"):
        if page not in out:
            _check(f"e3 {page} が残る", False)
            return
    _check("e3 2-6 面の見出しがすべて残る", True)
    _check("e4 CSS は既に注入済みなので追加されない",
           inject_page_one_v3_css(html) == html)


def main() -> int:
    print("C174: 単日 Page I 再生成のための swap 冪等化\n")
    print("(a) v2 / v3 どちらでも swap:")
    test_swap_v2_marker()
    test_swap_v3_marker_with_attrs()
    test_regex_matches_both()
    test_missing_section_raises()
    print()
    print("(b) 他面を壊さない:")
    test_other_pages_survive()
    test_swap_is_repeatable()
    print()
    print("(c) CSS 注入の冪等性:")
    test_css_injection_idempotent()
    test_css_marker_is_in_css()
    test_css_injected_when_absent()
    print()
    print("(d) --page-one-only の配線:")
    test_flag_parsed()
    test_page_one_only_does_not_call_v2()
    print()
    print("(e) 実データ回帰:")
    test_real_archive()
    print()
    print(f"=== {PASS} passed, {FAIL} failed ===")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
