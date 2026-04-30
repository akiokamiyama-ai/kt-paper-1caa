"""Unit tests for scripts/lib/drivers/rss.py.

Sprint 2 Step F: tests for ``_decode_html_entities()`` added to fix
Foresight feed's leaking ``&hellip;`` (HTML entities not decoded by
ET's XML parser, double-escaped by downstream html.escape()).

Run::

    python3 -m scripts.lib.drivers.test_rss
"""

from __future__ import annotations

import sys

from .rss import _decode_html_entities


PASS = 0
FAIL = 0


def _check(label: str, got, expected) -> bool:
    global PASS, FAIL
    ok = got == expected
    sym = "✓" if ok else "✗"
    print(f"  {sym} {label}  (got={got!r}, expected={expected!r})")
    if ok:
        PASS += 1
    else:
        FAIL += 1
    return ok


def main() -> int:
    print("_decode_html_entities unit tests")
    print()

    # Named HTML entities (the original Foresight bug).
    _check("e1 &hellip; → …", _decode_html_entities("&hellip;"), "…")
    _check("e2 &nbsp; → NBSP",
           _decode_html_entities("foo &nbsp; bar"), "foo   bar")

    # Single-pass behavior on doubly-escaped: per spec, &amp;hellip; → &hellip;
    # (NOT recursively decoded to …). This is documented behavior.
    _check(
        "e3 &amp;hellip; → &hellip; (single-pass, idempotent on second call)",
        _decode_html_entities("&amp;hellip;"),
        "&hellip;",
    )

    # XML standard entities (technically already handled by ET, but unescape
    # is idempotent — confirms it doesn't break already-decoded content).
    _check("e4 &quot;Hello&quot; → quoted",
           _decode_html_entities("&quot;Hello&quot;"), '"Hello"')
    _check("e5 &amp; → &", _decode_html_entities("Smith &amp; Co"), "Smith & Co")

    # Numeric entities.
    _check("e6 &#8217; → typographic apostrophe",
           _decode_html_entities("It&#8217;s"), "It’s")
    _check("e7 &#x2026; → … (hex numeric)",
           _decode_html_entities("etc&#x2026;"), "etc…")

    # Edge cases.
    _check("e8 None passes through", _decode_html_entities(None), None)
    _check("e9 empty string passes through", _decode_html_entities(""), "")
    _check(
        "e10 plain Japanese text unchanged",
        _decode_html_entities("通常の日本語テキスト"),
        "通常の日本語テキスト",
    )

    # Mixed pattern from spec.
    _check(
        "e11 mixed &amp;hellip;&hellip; → &hellip;…",
        _decode_html_entities("&amp;hellip;&hellip;"),
        "&hellip;…",
    )

    # Already-decoded content (idempotency).
    _check(
        "e12 already-decoded text idempotent",
        _decode_html_entities("foo … bar"),
        "foo … bar",
    )

    # Realistic Foresight description fragment.
    _check(
        "e13 Foresight-style truncation marker",
        _decode_html_entities(
            "イスラエルでは今年10月までに総選挙が実施される。"
            "[&#8230;]"
        ),
        "イスラエルでは今年10月までに総選挙が実施される。[…]",
    )

    print()
    print(f"=== {PASS} passed, {FAIL} failed ===")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
