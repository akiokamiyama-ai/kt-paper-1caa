"""Unit tests for C45 D2 — editorial が v3 swap 適用日に Page I を除外する判定.

`scripts.regen_front_page_v2._v3_swap_will_apply()` を一時 pivotal JSON で検証。
helper 単体の動作テスト。call site (main() の editorial build 部) は
helper の戻り値に応じて page_one_selected=None/result.selected を渡すだけの
小さな分岐なので unit test 対象は helper に集約する。

Run::

    python3 -m tests.test_editorial_v3_awareness
"""

from __future__ import annotations

import json
import sys
import tempfile
from datetime import date
from pathlib import Path

from scripts.regen_front_page_v2 import _v3_swap_will_apply

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


def _write_pivotal(tmp: Path, weeks: dict) -> Path:
    """Write a minimal monthly_pivotal.json for testing.

    `weeks` is e.g. {"W1": {"period": ["2026-05-24", "2026-05-30"], ...}}.
    Only the fields find_week_for_date() reads are required.
    """
    payload = {
        "current_month": "2026-05",
        "weeks": weeks,
    }
    path = tmp / "monthly_pivotal.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# (a) v3 適用日（週が登録されている）→ True
# ---------------------------------------------------------------------------

def test_v3_applies_when_date_in_registered_week():
    with tempfile.TemporaryDirectory() as tmp:
        p = _write_pivotal(Path(tmp), {
            "W1": {
                "theme": "AIと暗黙知",
                "period": ["2026-05-24", "2026-05-30"],
                "article": {"title": "T", "source": "S", "url": "u",
                            "published": "2026-04-13", "summary": "",
                            "key_quote": "", "key_quote_ja": "", "points": [],
                            "angles_hints": {}},
            },
        })
        # 週の中央
        _check(
            "a1 5/27 (W1 火曜) → v3 適用 True",
            _v3_swap_will_apply(date(2026, 5, 27), pivotal_path=p) is True,
        )
        # 週の境界（開始日）
        _check(
            "a2 5/24 (W1 日曜・開始) → v3 適用 True",
            _v3_swap_will_apply(date(2026, 5, 24), pivotal_path=p) is True,
        )
        # 週の境界（終了日）
        _check(
            "a3 5/30 (W1 土曜・終了) → v3 適用 True",
            _v3_swap_will_apply(date(2026, 5, 30), pivotal_path=p) is True,
        )


# ---------------------------------------------------------------------------
# (b) v3 不適用日（週外 / 未登録週）→ False
# ---------------------------------------------------------------------------

def test_v3_not_applies_outside_registered_week():
    with tempfile.TemporaryDirectory() as tmp:
        p = _write_pivotal(Path(tmp), {
            "W1": {
                "theme": "AIと暗黙知",
                "period": ["2026-05-24", "2026-05-30"],
                "article": {"title": "T", "source": "S", "url": "u",
                            "published": "2026-04-13", "summary": "",
                            "key_quote": "", "key_quote_ja": "", "points": [],
                            "angles_hints": {}},
            },
        })
        _check(
            "b1 5/23 (W1 開始の前日) → v3 不適用 False",
            _v3_swap_will_apply(date(2026, 5, 23), pivotal_path=p) is False,
        )
        _check(
            "b2 5/31 (W1 終了の翌日) → v3 不適用 False",
            _v3_swap_will_apply(date(2026, 5, 31), pivotal_path=p) is False,
        )
        _check(
            "b3 4/15 (登録週から大きく離れる) → v3 不適用 False",
            _v3_swap_will_apply(date(2026, 4, 15), pivotal_path=p) is False,
        )


def test_v3_not_applies_when_no_weeks_registered():
    with tempfile.TemporaryDirectory() as tmp:
        p = _write_pivotal(Path(tmp), {})  # weeks 空
        _check(
            "b4 weeks 空 → 全日 v3 不適用 False",
            _v3_swap_will_apply(date(2026, 5, 27), pivotal_path=p) is False,
        )


# ---------------------------------------------------------------------------
# (c) Pivotal load 失敗時の保守的 fallback（False）
# ---------------------------------------------------------------------------

def test_v3_false_when_pivotal_missing():
    """pivotal.json 不在 → False（既存 v2 挙動を維持、Page I 含む）."""
    with tempfile.TemporaryDirectory() as tmp:
        missing = Path(tmp) / "no_such_file.json"
        _check(
            "c1 pivotal.json 不在 → False（保守的 fallback）",
            _v3_swap_will_apply(date(2026, 5, 27), pivotal_path=missing) is False,
        )


def test_v3_false_when_pivotal_corrupt():
    """壊れた JSON → False（既存 v2 挙動を維持）."""
    with tempfile.TemporaryDirectory() as tmp:
        corrupt = Path(tmp) / "corrupt.json"
        corrupt.write_text("{not valid json", encoding="utf-8")
        _check(
            "c2 壊れた JSON → False（例外捕捉、保守的 fallback）",
            _v3_swap_will_apply(date(2026, 5, 27), pivotal_path=corrupt) is False,
        )


def test_v3_false_when_pivotal_wrong_shape():
    """期待外の構造 → False（既存 v2 挙動を維持）."""
    with tempfile.TemporaryDirectory() as tmp:
        wrong = Path(tmp) / "wrong.json"
        wrong.write_text(json.dumps({"foo": "bar"}), encoding="utf-8")
        # 構造不正は load_monthly_pivotal が例外、もしくは find_week_for_date が
        # 安全に None を返すケースの両方を許容する（どちらでも結果は False）。
        _check(
            "c3 構造不正な JSON → False",
            _v3_swap_will_apply(date(2026, 5, 27), pivotal_path=wrong) is False,
        )


# ---------------------------------------------------------------------------
# (d) 5/29 (今日) — 実 pivotal で v3 適用確認（D2 真因対応の対象日）
# ---------------------------------------------------------------------------

def test_v3_applies_on_2026_05_29_with_real_pivotal():
    """実 data/monthly_pivotal.json で 5/29 が W1 内にあることを確認.

    C45 D2 で問題視された 5/29 朝刊が editorial の Page I 除外対象であることを
    実環境で念押し（pivotal_path 省略 → DEFAULT_PIVOTAL_PATH を使う）。
    """
    _check(
        "d1 5/29 (実 pivotal) → v3 適用 True（C45 真因日）",
        _v3_swap_will_apply(date(2026, 5, 29)) is True,
    )


def main() -> int:
    print("C45 D2 editorial v3-awareness tests (2026-05-29)")
    print()
    print("(a) v3 適用日（週内）:")
    test_v3_applies_when_date_in_registered_week()
    print()
    print("(b) v3 不適用日（週外 / 未登録）:")
    test_v3_not_applies_outside_registered_week()
    test_v3_not_applies_when_no_weeks_registered()
    print()
    print("(c) Pivotal load 失敗時の保守的 fallback:")
    test_v3_false_when_pivotal_missing()
    test_v3_false_when_pivotal_corrupt()
    test_v3_false_when_pivotal_wrong_shape()
    print()
    print("(d) 5/29 実 pivotal で v3 適用確認:")
    test_v3_applies_on_2026_05_29_with_real_pivotal()
    print()
    print(f"=== {PASS} passed, {FAIL} failed ===")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
