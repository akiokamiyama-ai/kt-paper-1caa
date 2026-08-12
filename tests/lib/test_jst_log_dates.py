"""ログの日付基準が JST に統一されていることの検証 (C159, Sprint 13, 2026-08-12).

背景
----
GHA runner は UTC。cron は 17:37 UTC（= 02:37 JST 翌日）に起動するため、
``date.today()`` を素で使うとログのファイル名が紙面日付より 1 日古くなる。
同じ事故が 3 回起きた（llm_usage / stage2_shadow / scores）ため、
実装を ``scripts/lib/jst.py`` に一本化し、本テストで回帰を防ぐ。

Tests:
  a) jst_today がタイムゾーン境界で正しく JST 日付を返す
  b) 各ログの既定パスが JST 基準
  c) writer と reader が同じ基準（片方だけ UTC だと恒久ギャップになる）
  d) scripts/ に素の date.today() が残っていない（回帰防止）
  e) prune 窓（8 日）が cache 窓（7 日）より広い

Run::

    python3 -m tests.lib.test_jst_log_dates
"""

from __future__ import annotations

import re
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from scripts.lib.jst import JST, jst_now_iso, jst_today

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

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
# (a) jst_today の境界挙動
# ---------------------------------------------------------------------------

def test_jst_today_crosses_date_boundary():
    """cron 起動時刻（17:37 UTC）では UTC と JST で日付が 1 日ずれる."""
    utc_moment = datetime(2026, 8, 12, 17, 37, tzinfo=ZoneInfo("UTC"))
    _check("a1 17:37 UTC は UTC では 8/12", utc_moment.date() == date(2026, 8, 12))
    _check("a2 同じ瞬間が JST では 8/13（紙面日付）",
           utc_moment.astimezone(JST).date() == date(2026, 8, 13))


def test_jst_today_returns_date():
    d = jst_today()
    _check("a3 jst_today は date を返す", isinstance(d, date))


def test_jst_now_iso_has_no_tz_suffix():
    s = jst_now_iso()
    ok = re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", s) is not None
    _check("a4 jst_now_iso は秒精度・tz 接尾辞なし", ok, f"got {s}")


# ---------------------------------------------------------------------------
# (b) 各ログの既定パスが JST 基準
# ---------------------------------------------------------------------------

def test_all_log_paths_use_jst():
    """UTC では 8/12、JST では 8/13 になる瞬間で各ログのパスを確認する."""
    from scripts.selector import page2, page3, stage2, stage3

    frozen = datetime(2026, 8, 12, 17, 37, tzinfo=ZoneInfo("UTC"))

    class _FrozenDT(datetime):
        @classmethod
        def now(cls, tz=None):
            return frozen.astimezone(tz) if tz else frozen.replace(tzinfo=None)

    with patch("scripts.lib.jst.datetime", _FrozenDT):
        cases = [
            ("scores (stage2 = 本番の writer)", stage2._scores_log_path().name,
             "scores_2026-08-13.json"),
            ("scores (stage3 = CLI)", stage3._scores_log_path().name,
             "scores_2026-08-13.json"),
            ("page2_scores", page2._page2_log_path().name,
             "page2_scores_2026-08-13.json"),
            ("page3_selection", page3._page3_log_path().name,
             "page3_selection_2026-08-13.json"),
        ]
        for label, got, want in cases:
            _check(f"b {label} が JST 日付", got == want, f"got {got}")


def test_llm_usage_and_shadow_still_jst():
    """先に JST 化されていた 2 つが共通ヘルパ移行後も JST のままか."""
    from scripts.lib import llm_usage
    from scripts.selector import stage2_shadow

    _check("b5 llm_usage._jst_today は jst_today と同一関数",
           llm_usage._jst_today is jst_today)
    _check("b6 stage2_shadow._jst_today も同一関数",
           stage2_shadow._jst_today is jst_today)


# ---------------------------------------------------------------------------
# (c) writer と reader が同じ基準
# ---------------------------------------------------------------------------

def test_scores_writer_and_cache_reader_agree():
    """C135 cache の reader が writer と同じ日付基準を使うこと。

    片方だけ UTC だと、reader は writer が書いた最新ファイルを永久に
    読み落とす（恒久 1 日ギャップ）。
    """
    from scripts.selector import stage2

    frozen = datetime(2026, 8, 12, 17, 37, tzinfo=ZoneInfo("UTC"))

    class _FrozenDT(datetime):
        @classmethod
        def now(cls, tz=None):
            return frozen.astimezone(tz) if tz else frozen.replace(tzinfo=None)

    seen: list[str] = []
    with patch("scripts.lib.jst.datetime", _FrozenDT):
        writer_name = stage2._scores_log_path().name

        class _FakeDir:
            def __truediv__(self, name):
                seen.append(name)
                return Path("/nonexistent") / name

        stage2._load_recent_scores(lookback_days=7, exclude_today=True,
                                   log_dir=_FakeDir())

    _check("c1 writer は JST 日付に書く", writer_name == "scores_2026-08-13.json",
           f"got {writer_name}")
    # exclude_today=True なので reader は 8/12 から 7 日遡る
    want = {f"scores_{(date(2026, 8, 13) - timedelta(days=o)).isoformat()}.json"
            for o in range(7, 0, -1)}
    _check("c2 reader も JST 基準で遡る（writer と同一 anchor）",
           set(seen) == want, f"got {sorted(seen)[:3]}...")
    _check("c3 reader の窓に writer の当日ファイルは含まない（自己衝突回避）",
           writer_name not in seen)


# ---------------------------------------------------------------------------
# (d) 回帰防止: 素の date.today() が残っていない
# ---------------------------------------------------------------------------

def test_no_bare_date_today_in_scripts():
    """scripts/ の実コードに date.today() が無いこと（コメント・テストは除外）."""
    out = subprocess.run(
        ["grep", "-rn", r"date\.today()", "--include=*.py", "scripts/"],
        cwd=PROJECT_ROOT, capture_output=True, text=True,
    ).stdout.splitlines()
    offenders = []
    for line in out:
        try:
            path, _lineno, code = line.split(":", 2)
        except ValueError:
            continue
        if "/test" in path:
            continue
        stripped = code.strip()
        # コメント行 / docstring 内の言及は対象外
        if stripped.startswith("#") or "``date.today()``" in code:
            continue
        offenders.append(line)
    _check("d1 scripts/ の実コードに素の date.today() が無い",
           not offenders, f"offenders={offenders[:3]}")


# ---------------------------------------------------------------------------
# (e) prune 窓 と cache 窓 の関係
# ---------------------------------------------------------------------------

def test_prune_window_wider_than_cache_window():
    """daily.yml の prune（8 日）が cache lookback（7 日）より広いこと。

    逆転すると cache が要求する最古のログを prune が消してしまう。
    """
    from scripts.selector.stage2 import DEFAULT_CACHE_LOOKBACK_DAYS

    wf = (PROJECT_ROOT / ".github" / "workflows" / "daily.yml").read_text(encoding="utf-8")
    m = re.search(r"date -d '(\d+) days ago'", wf)
    _check("e1 daily.yml に prune の日数指定がある", m is not None)
    if not m:
        return
    prune_days = int(m.group(1))
    _check(f"e2 prune {prune_days} 日 > cache lookback {DEFAULT_CACHE_LOOKBACK_DAYS} 日",
           prune_days > DEFAULT_CACHE_LOOKBACK_DAYS,
           f"prune={prune_days}, cache={DEFAULT_CACHE_LOOKBACK_DAYS}")


def test_prune_cutoff_is_jst_based():
    """prune の CUTOFF が JST で計算されていること（ファイル名も JST なので）."""
    wf = (PROJECT_ROOT / ".github" / "workflows" / "daily.yml").read_text(encoding="utf-8")
    _check("e3 prune の CUTOFF が TZ='Asia/Tokyo' 基準",
           "TZ='Asia/Tokyo' date -d '8 days ago'" in wf)


def main() -> int:
    print("JST ログ日付統一 tests (C159, Sprint 13, 2026-08-12)")
    print()
    print("(a) jst_today の境界挙動:")
    test_jst_today_crosses_date_boundary()
    test_jst_today_returns_date()
    test_jst_now_iso_has_no_tz_suffix()
    print()
    print("(b) 各ログの既定パス:")
    test_all_log_paths_use_jst()
    test_llm_usage_and_shadow_still_jst()
    print()
    print("(c) writer / reader の基準一致:")
    test_scores_writer_and_cache_reader_agree()
    print()
    print("(d) 回帰防止:")
    test_no_bare_date_today_in_scripts()
    print()
    print("(e) prune 窓との整合:")
    test_prune_window_wider_than_cache_window()
    test_prune_cutoff_is_jst_based()
    print()
    print(f"=== {PASS} passed, {FAIL} failed ===")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
