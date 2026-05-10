"""Unit tests for Page IV rotation の fence-post error 修正（Sprint 6 Phase 2）.

5/4-5/10 の page4_urls 観察で、ROTATION_DAYS=3 の意図に反して 4 日連続同じ
pool が表示される fence-post error を発見（5/6-5/9 が同一 pool）。
``is_pool_active`` を ``>=`` から ``>`` に変更して 3 日サイクルを正しく適用。

Run::

    python3 -m tests.test_page4_rotation
"""

from __future__ import annotations

import sys
from datetime import date

from scripts.page4.article_rotator import (
    ROTATION_DAYS,
    is_pool_active,
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


def _make_rotation(generated_on: date, expires_on: date, pool_size: int = 3) -> dict:
    return {
        "pool": [f"https://example.com/article-{i}" for i in range(pool_size)],
        "generated_on": generated_on.isoformat(),
        "expires_on": expires_on.isoformat(),
    }


# ---------------------------------------------------------------------------
# (a) 3 日サイクル：generated_on, +1, +2 で active、+3 で inactive
# ---------------------------------------------------------------------------

def test_active_on_generation_day():
    rotation = _make_rotation(date(2026, 5, 6), date(2026, 5, 9))
    _check(
        "a1 generated_on (5/6) は active",
        is_pool_active(rotation, date(2026, 5, 6)),
    )


def test_active_on_day_plus_1():
    rotation = _make_rotation(date(2026, 5, 6), date(2026, 5, 9))
    _check(
        "a2 generated_on + 1 (5/7) は active",
        is_pool_active(rotation, date(2026, 5, 7)),
    )


def test_active_on_day_plus_2():
    rotation = _make_rotation(date(2026, 5, 6), date(2026, 5, 9))
    _check(
        "a3 generated_on + 2 (5/8) は active",
        is_pool_active(rotation, date(2026, 5, 8)),
    )


# ---------------------------------------------------------------------------
# (b) fence-post fix: expires_on 当日 (= generated_on + 3) は inactive
# ---------------------------------------------------------------------------

def test_inactive_on_expires_on_day():
    """fence-post fix の本丸：expires_on 当日に inactive となる."""
    rotation = _make_rotation(date(2026, 5, 6), date(2026, 5, 9))
    _check(
        "b1 expires_on (5/9) は inactive (fence-post fix)",
        not is_pool_active(rotation, date(2026, 5, 9)),
        "before fix: active になっていた",
    )


def test_inactive_after_expires():
    rotation = _make_rotation(date(2026, 5, 6), date(2026, 5, 9))
    _check(
        "b2 expires_on の翌日 (5/10) も inactive",
        not is_pool_active(rotation, date(2026, 5, 10)),
    )


# ---------------------------------------------------------------------------
# (c) 既存 page4_rotation.json（5/10 generated, 5/13 expires_on）の検証
# ---------------------------------------------------------------------------

def test_current_rotation_state():
    """5/10 生成 / expires_on 5/13 の rotation で、5/10〜5/12 active、5/13 から inactive."""
    rotation = _make_rotation(date(2026, 5, 10), date(2026, 5, 13))
    _check(
        "c1 5/10 (generated_on) は active",
        is_pool_active(rotation, date(2026, 5, 10)),
    )
    _check(
        "c2 5/11 は active",
        is_pool_active(rotation, date(2026, 5, 11)),
    )
    _check(
        "c3 5/12 は active",
        is_pool_active(rotation, date(2026, 5, 12)),
    )
    _check(
        "c4 5/13 (expires_on) は inactive (新 pool 生成へ)",
        not is_pool_active(rotation, date(2026, 5, 13)),
    )


# ---------------------------------------------------------------------------
# (d) ROTATION_DAYS と週 active 日数の整合
# ---------------------------------------------------------------------------

def test_rotation_days_matches_active_window():
    """ROTATION_DAYS = N なら、active 日数も正確に N 日."""
    generated = date(2026, 6, 1)
    expires = generated.replace(day=generated.day + ROTATION_DAYS)
    rotation = _make_rotation(generated, expires)
    active_days = sum(
        1 for i in range(ROTATION_DAYS + 2)
        if is_pool_active(rotation, generated.replace(day=generated.day + i))
    )
    _check(
        f"d1 active 日数 = ROTATION_DAYS ({ROTATION_DAYS})",
        active_days == ROTATION_DAYS,
        f"got active_days={active_days}",
    )


# ---------------------------------------------------------------------------
# (e) edge cases: empty pool / missing expires_on
# ---------------------------------------------------------------------------

def test_empty_pool_inactive():
    rotation = {"pool": [], "expires_on": "2099-01-01", "generated_on": "2026-05-01"}
    _check(
        "e1 空 pool は inactive (v1.1 既存挙動)",
        not is_pool_active(rotation, date(2026, 5, 10)),
    )


def test_missing_expires_inactive():
    rotation = {"pool": ["url"], "generated_on": "2026-05-10"}
    _check(
        "e2 expires_on 欠落は inactive",
        not is_pool_active(rotation, date(2026, 5, 10)),
    )


def main() -> int:
    print("Page IV rotation fence-post fix テスト (Sprint 6 Phase 2, 2026-05-10)")
    print()
    print("(a) 3 日サイクル正常動作:")
    test_active_on_generation_day()
    test_active_on_day_plus_1()
    test_active_on_day_plus_2()
    print()
    print("(b) fence-post fix の本丸:")
    test_inactive_on_expires_on_day()
    test_inactive_after_expires()
    print()
    print("(c) 既存 page4_rotation.json (5/10 generated) の検証:")
    test_current_rotation_state()
    print()
    print("(d) ROTATION_DAYS と active 日数の整合:")
    test_rotation_days_matches_active_window()
    print()
    print("(e) edge cases:")
    test_empty_pool_inactive()
    test_missing_expires_inactive()
    print()
    print(f"=== {PASS} passed, {FAIL} failed ===")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
