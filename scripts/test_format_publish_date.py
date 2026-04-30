"""Unit tests for ``_format_publish_date_ja`` in regen_front_page_v2.

Run::

    python3 -m scripts.test_format_publish_date

Covers:

* Full ISO 8601 with UTC offset → JST conversion
* Full ISO 8601 with "Z" suffix
* Full ISO 8601 already in JST
* Date-only "YYYY-MM-DD" (assumed UTC midnight, JST = same day 09:00)
* UTC near-midnight → JST next day (timezone shift)
* None / empty / malformed → empty string
"""

from __future__ import annotations

import sys

from .regen_front_page_v2 import _format_publish_date_ja


PASS = 0
FAIL = 0


def _check(label: str, got: str, expected: str) -> bool:
    global PASS, FAIL
    ok = got == expected
    sym = "✓" if ok else "✗"
    detail = f"got={got!r}, expected={expected!r}"
    print(f"  {sym} {label}  ({detail})")
    if ok:
        PASS += 1
    else:
        FAIL += 1
    return ok


def main() -> int:
    print("_format_publish_date_ja unit tests")
    print()

    # 1. Full ISO 8601 with UTC offset (typical RSS pub_date)
    _check(
        "p1 ISO 8601 UTC+0 → JST same day",
        _format_publish_date_ja("2026-04-28T10:30:00+00:00"),
        "2026年4月28日",
    )

    # 2. Full ISO with "Z" suffix
    _check(
        "p2 ISO 8601 'Z' suffix → JST same day",
        _format_publish_date_ja("2026-04-28T10:30:00Z"),
        "2026年4月28日",
    )

    # 3. Already JST (+09:00)
    _check(
        "p3 ISO 8601 already JST",
        _format_publish_date_ja("2026-04-28T15:00:00+09:00"),
        "2026年4月28日",
    )

    # 4. Date-only string
    _check(
        "p4 date-only 'YYYY-MM-DD'",
        _format_publish_date_ja("2026-04-28"),
        "2026年4月28日",
    )

    # 5. UTC near-midnight → JST next day (4/28 22:00 UTC = 4/29 07:00 JST)
    _check(
        "p5 UTC late evening → JST next day",
        _format_publish_date_ja("2026-04-28T22:00:00+00:00"),
        "2026年4月29日",
    )

    # 6. None → empty
    _check("p6 None → empty string", _format_publish_date_ja(None), "")

    # 7. Empty string → empty
    _check("p7 empty string → empty string", _format_publish_date_ja(""), "")

    # 8. Malformed → empty
    _check(
        "p8 malformed string → empty string",
        _format_publish_date_ja("not-a-date"),
        "",
    )

    # 9. Naive datetime (no timezone, assumed UTC)
    _check(
        "p9 naive datetime (no tz) treated as UTC",
        _format_publish_date_ja("2026-04-28T10:30:00"),
        "2026年4月28日",
    )

    # 10. RFC-3339 with offset (rare format from some feeds)
    _check(
        "p10 ISO with -05:00 offset (US/Eastern late evening → JST next day)",
        _format_publish_date_ja("2026-04-28T22:00:00-05:00"),  # = 4/29 03:00 UTC = 4/29 12:00 JST
        "2026年4月29日",
    )

    print()
    print(f"=== {PASS} passed, {FAIL} failed ===")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
