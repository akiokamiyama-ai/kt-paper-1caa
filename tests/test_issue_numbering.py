"""Unit tests for issue_number() — Vol/No 動的採番（Sprint 5 ポストモーメント、2026-05-06）.

Tests:
  a) 既存 archive を target にすると通番がずれない（再生成時の挙動）
  b) 欠番（4/26-4/28）はカウントしない
  c) 当日 archive が無い（新規生成時）→ 既存数 + 1
  d) 年が変わると Vol が +1、No は 1 から開始
  e) `_` で始まるファイル（_logo_preview など）は除外

Run::

    python3 -m tests.test_issue_numbering
"""

from __future__ import annotations

import sys
import tempfile
from datetime import date
from pathlib import Path

from scripts.regen_front_page_v2 import issue_number

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


def _make_archive_dir_2026(tmp: Path) -> Path:
    """2026 年の 9 件 archive をモック（合宿初日 + GW + Sprint 5）."""
    archive_dir = tmp / "archive"
    archive_dir.mkdir()
    for d in [
        "2026-04-25", "2026-04-29", "2026-04-30",
        "2026-05-01", "2026-05-02", "2026-05-03",
        "2026-05-04", "2026-05-05", "2026-05-06",
    ]:
        (archive_dir / f"{d}.html").touch()
    return archive_dir


# ---------------------------------------------------------------------------
# (a) 既存 archive: 再生成しても通番がずれない
# ---------------------------------------------------------------------------

def test_existing_archive_first():
    with tempfile.TemporaryDirectory() as tmp:
        archive_dir = _make_archive_dir_2026(Path(tmp))
        result = issue_number(date(2026, 4, 25), archive_dir)
        _check(
            "a1 4/25 (Tribune 開始日) → Vol. 1, No. 1",
            result == (1, 1),
            f"got {result}",
        )


def test_existing_archive_recent():
    with tempfile.TemporaryDirectory() as tmp:
        archive_dir = _make_archive_dir_2026(Path(tmp))
        result = issue_number(date(2026, 5, 6), archive_dir)
        _check(
            "a2 5/6 (現状最新) → Vol. 1, No. 9",
            result == (1, 9),
            f"got {result}",
        )


def test_re_generation_does_not_increment():
    """既存 archive を再生成しても番号がずれない (5/1 = 4 番目)."""
    with tempfile.TemporaryDirectory() as tmp:
        archive_dir = _make_archive_dir_2026(Path(tmp))
        result = issue_number(date(2026, 5, 1), archive_dir)
        _check(
            "a3 5/1 既存 archive 再生成 → Vol. 1, No. 4 (ずれない)",
            result == (1, 4),
            f"got {result}",
        )


# ---------------------------------------------------------------------------
# (b) 欠番（4/26-4/28）はカウントしない
# ---------------------------------------------------------------------------

def test_existing_archive_with_gap():
    with tempfile.TemporaryDirectory() as tmp:
        archive_dir = _make_archive_dir_2026(Path(tmp))
        result = issue_number(date(2026, 4, 29), archive_dir)
        _check(
            "b1 4/29 (4/26-4/28 欠番をスキップ) → Vol. 1, No. 2",
            result == (1, 2),
            f"got {result}",
        )


# ---------------------------------------------------------------------------
# (c) 当日 archive が無い（新規生成時）→ 既存数 + 1
# ---------------------------------------------------------------------------

def test_new_archive_increments():
    """5/7 archive はまだ無い → 既存 9 件 + 1 = No. 10."""
    with tempfile.TemporaryDirectory() as tmp:
        archive_dir = _make_archive_dir_2026(Path(tmp))
        result = issue_number(date(2026, 5, 7), archive_dir)
        _check(
            "c1 5/7 新規生成 → Vol. 1, No. 10 (既存 9 + 1)",
            result == (1, 10),
            f"got {result}",
        )


# ---------------------------------------------------------------------------
# (d) 年が変わると Vol が +1、No は 1 から開始
# ---------------------------------------------------------------------------

def test_year_boundary():
    with tempfile.TemporaryDirectory() as tmp:
        archive_dir = Path(tmp) / "archive"
        archive_dir.mkdir()
        # 2026 年の archive のみ
        (archive_dir / "2026-04-25.html").touch()
        (archive_dir / "2026-12-31.html").touch()

        result = issue_number(date(2027, 1, 1), archive_dir)
        _check(
            "d1 2027-01-01 (年明け、2027 年 archive 0 件) → Vol. 2, No. 1",
            result == (2, 1),
            f"got {result}",
        )


def test_year_boundary_with_existing_2027():
    with tempfile.TemporaryDirectory() as tmp:
        archive_dir = Path(tmp) / "archive"
        archive_dir.mkdir()
        (archive_dir / "2026-12-31.html").touch()
        (archive_dir / "2027-01-01.html").touch()
        (archive_dir / "2027-01-02.html").touch()

        result = issue_number(date(2027, 1, 15), archive_dir)
        _check(
            "d2 2027-01-15 (2027 年既存 2 件 + 新規) → Vol. 2, No. 3",
            result == (2, 3),
            f"got {result}",
        )


# ---------------------------------------------------------------------------
# (e) `_` で始まるファイル（_logo_preview など）は除外
# ---------------------------------------------------------------------------

def test_underscore_files_excluded():
    with tempfile.TemporaryDirectory() as tmp:
        archive_dir = Path(tmp) / "archive"
        archive_dir.mkdir()
        (archive_dir / "2026-04-25.html").touch()
        (archive_dir / "_logo_preview.html").touch()
        (archive_dir / "_monday_session.html").touch()

        result = issue_number(date(2026, 4, 25), archive_dir)
        _check(
            "e1 _ で始まるファイルはカウントしない → Vol. 1, No. 1",
            result == (1, 1),
            f"got {result}",
        )


def main() -> int:
    print("issue_number() unit tests (Sprint 5 ポストモーメント, 2026-05-06)")
    print()
    print("(a) 既存 archive: 再生成しても通番がずれない:")
    test_existing_archive_first()
    test_existing_archive_recent()
    test_re_generation_does_not_increment()
    print()
    print("(b) 欠番（4/26-4/28）はカウントしない:")
    test_existing_archive_with_gap()
    print()
    print("(c) 当日 archive が無い（新規生成時）→ 既存数 + 1:")
    test_new_archive_increments()
    print()
    print("(d) 年が変わると Vol が +1、No は 1 から開始:")
    test_year_boundary()
    test_year_boundary_with_existing_2027()
    print()
    print("(e) `_` で始まるファイル（_logo_preview など）は除外:")
    test_underscore_files_excluded()
    print()
    print(f"=== {PASS} passed, {FAIL} failed ===")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
