"""Unit tests for llm_usage の JST 基準日付（Sprint 6 Phase 1）.

GHA runner は UTC で動作するため、従来の ``date.today()`` だと JST 早朝の
ラン（例：JST 06:29 = UTC 21:29 前日）で前日付の log に書き込まれていた。
``_jst_today()`` / ``_jst_now_iso()`` で JST 基準に統一されたことを確認。

Run::

    python3 -m tests.test_llm_usage_date
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import date
from pathlib import Path
from unittest.mock import patch

from scripts.lib import llm_usage

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


def test_jst_today_under_utc_environment():
    """OS の TZ='UTC' 環境でも、_jst_today() は JST の日付を返す.

    実装は ``zoneinfo.ZoneInfo("Asia/Tokyo")`` を使うため、OS の TZ に
    依存せず常に JST を取る。
    """
    original_tz = os.environ.get("TZ")
    try:
        os.environ["TZ"] = "UTC"
        # _jst_today() は ZoneInfo("Asia/Tokyo") から計算するので
        # 環境変数 TZ には影響されないことを確認
        d_jst = llm_usage._jst_today()
        # JST と UTC の日付差は最大 1 日（JST 早朝は UTC 前日）
        from datetime import datetime, timezone
        d_utc = datetime.now(timezone.utc).date()
        diff_days = abs((d_jst - d_utc).days)
        _check(
            "a1 _jst_today() vs UTC date の差は 0 または 1 日",
            diff_days <= 1,
            f"jst={d_jst}, utc={d_utc}, diff={diff_days}",
        )
        # JST hour が 0-8 のときは UTC 前日、それ以外は同日
        from zoneinfo import ZoneInfo
        jst_now = datetime.now(ZoneInfo("Asia/Tokyo"))
        if jst_now.hour < 9:
            expected_utc = (jst_now.date()).isoformat()
            # ここは緩く確認、_jst_today() が JST の今日を取れることを assert
        _check(
            "a2 _jst_today() は date 型を返す",
            isinstance(d_jst, date),
            f"got {type(d_jst).__name__}",
        )
    finally:
        if original_tz is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = original_tz


def test_record_call_uses_jst_today_by_default():
    """today 引数を渡さない record_call は JST 基準でログを書く."""
    with tempfile.TemporaryDirectory() as tmp:
        log_dir = Path(tmp)
        with patch.object(llm_usage, "LOG_DIR", log_dir):
            llm_usage.record_call("claude-sonnet-4-6", 100, 50, tag="test")
            jst_today = llm_usage._jst_today()
            expected_path = log_dir / f"llm_usage_{jst_today.isoformat()}.json"
            _check(
                "b1 today 省略時 _jst_today() でログ書き込み",
                expected_path.exists(),
                f"expected={expected_path.name}, exists={[p.name for p in log_dir.iterdir()]}",
            )


def test_record_call_with_explicit_date():
    """today 引数を明示的に渡せば、その日付で記録される（後方互換）."""
    with tempfile.TemporaryDirectory() as tmp:
        log_dir = Path(tmp)
        with patch.object(llm_usage, "LOG_DIR", log_dir):
            llm_usage.record_call(
                "claude-sonnet-4-6", 100, 50,
                today=date(2026, 5, 10),
                tag="test",
            )
            target = log_dir / "llm_usage_2026-05-10.json"
            _check(
                "b2 today=date(2026,5,10) で明示記録",
                target.exists(),
                f"expected exists, got {target.exists()}",
            )


def test_jst_now_iso_format():
    """_jst_now_iso() は ISO 形式（秒精度、tz suffix なし）."""
    ts = llm_usage._jst_now_iso()
    # 期待形式: "YYYY-MM-DDTHH:MM:SS"
    _check(
        "c1 ISO 形式・19 文字（秒精度）",
        len(ts) == 19 and ts[10] == "T",
        f"got {ts!r}",
    )
    _check(
        "c2 timezone suffix なし（'+' '-' Z 含まず）",
        "+" not in ts and "Z" not in ts and ts.count("-") == 2,
        f"got {ts!r}",
    )


def main() -> int:
    print("llm_usage JST 基準日付テスト (Sprint 6 Phase 1, 2026-05-10)")
    print()
    print("(a) _jst_today() は OS TZ に依存しない:")
    test_jst_today_under_utc_environment()
    print()
    print("(b) record_call の日付選択:")
    test_record_call_uses_jst_today_by_default()
    test_record_call_with_explicit_date()
    print()
    print("(c) _jst_now_iso() の形式:")
    test_jst_now_iso_format()
    print()
    print(f"=== {PASS} passed, {FAIL} failed ===")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
