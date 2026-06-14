"""Unit tests for scripts/analytics/layer3_diagnosis.py (C85 Sub-Step 5b).

Phase B Step 4 運用ツール。fixture scores_*.json を生成して、5 判定パターン
それぞれが想定通り検出されることを確認。

Run::

    python3 -m tests.test_layer3_diagnosis
"""

from __future__ import annotations

import json
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

from scripts.analytics import layer3_diagnosis as lyd

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


def _write_scores(
    log_dir: Path, day: date, entries: dict[str, dict],
) -> None:
    """logs/scores_YYYY-MM-DD.json 形式で fixture 書き込み."""
    path = log_dir / f"scores_{day.isoformat()}.json"
    path.write_text(
        json.dumps({"evaluations_by_url": entries}, ensure_ascii=False),
        encoding="utf-8",
    )


def _entry(
    *,
    source: str,
    final_score: float | None = 50.0,
    layer: int | None = 3,
    selected_for_page: str | None = None,
    selection_reason: str | None = None,
    evaluation_mode: str = "sonnet_full",
    caller: str = "page1_master",
) -> dict:
    return {
        "source_name": source,
        "final_score": final_score,
        "layer": layer,
        "evaluation_mode": evaluation_mode,
        "caller": caller,
        "selected_for_page": selected_for_page,
        "selection_reason": selection_reason,
        "美意識1": 6, "美意識3": 7, "美意識5": 5, "美意識6": 4, "美意識8": 3,
    }


# ---------------------------------------------------------------------------
# (a) collect_diagnosis 基本動作
# ---------------------------------------------------------------------------

def test_collect_filters_to_layer_3_by_default():
    with tempfile.TemporaryDirectory() as td:
        ld = Path(td)
        d0 = date(2026, 6, 17)
        _write_scores(ld, d0, {
            "https://x/1": _entry(source="Foreign Affairs（CFR）", final_score=55, layer=3),
            "https://x/2": _entry(source="BBC Business", final_score=40, layer=1),
        })
        out = lyd.collect_diagnosis(start=d0, end=d0, log_dir=ld)
    _check(
        "a1 デフォルト layer=3 で BBC（layer 1）は集計対象外",
        "Foreign Affairs（CFR）" in out and "BBC Business" not in out,
        f"got sources={list(out.keys())}",
    )


def test_collect_layer_filter_none_includes_all():
    with tempfile.TemporaryDirectory() as td:
        ld = Path(td)
        d0 = date(2026, 6, 17)
        _write_scores(ld, d0, {
            "https://x/1": _entry(source="Foreign Affairs（CFR）", layer=3),
            "https://x/2": _entry(source="BBC Business", layer=1),
        })
        out = lyd.collect_diagnosis(start=d0, end=d0, layer_filter=None, log_dir=ld)
    _check(
        "a2 layer_filter=None で全層集計",
        len(out) == 2 and "BBC Business" in out,
    )


def test_collect_source_substring_filter():
    with tempfile.TemporaryDirectory() as td:
        ld = Path(td)
        d0 = date(2026, 6, 17)
        _write_scores(ld, d0, {
            "https://x/1": _entry(source="Foreign Affairs（CFR）", layer=3),
            "https://x/2": _entry(source="Foreign Policy", layer=3),
            "https://x/3": _entry(source="Project Syndicate", layer=3),
        })
        out = lyd.collect_diagnosis(
            start=d0, end=d0, source_filter="Foreign", log_dir=ld,
        )
    _check(
        "a3 source_filter='Foreign' で 2 件マッチ（Affairs + Policy）",
        len(out) == 2 and "Foreign Affairs（CFR）" in out and "Foreign Policy" in out,
    )


def test_collect_handles_missing_log():
    with tempfile.TemporaryDirectory() as td:
        ld = Path(td)
        d0 = date(2026, 6, 17)
        # ログを書かない
        out = lyd.collect_diagnosis(start=d0, end=d0, log_dir=ld)
    _check("a4 ログ欠落 → 空 dict", out == {})


def test_collect_multi_day_aggregates():
    """3 日分のログを集約、days_observed が正しい."""
    with tempfile.TemporaryDirectory() as td:
        ld = Path(td)
        d0 = date(2026, 6, 17)
        for i in range(3):
            _write_scores(ld, d0 + timedelta(days=i), {
                f"https://x/{i}": _entry(
                    source="Foreign Affairs（CFR）",
                    final_score=50 + i * 5,
                ),
            })
        out = lyd.collect_diagnosis(
            start=d0, end=d0 + timedelta(days=2), log_dir=ld,
        )
        d = out["Foreign Affairs（CFR）"]
    _check(
        "a5 3 日分集約: 3 件評価、days_observed=3, days_fetched=3",
        d.total_articles_evaluated == 3 and d.days_observed == 3
        and d.days_fetched == 3 and d.days_with_zero_fetch == 0,
        f"got eval={d.total_articles_evaluated} obs={d.days_observed} "
        f"fetched={d.days_fetched} zero={d.days_with_zero_fetch}",
    )


# ---------------------------------------------------------------------------
# (b) パターン判定
# ---------------------------------------------------------------------------

def test_pattern_low_score():
    """final_score < 40 連発 → low_score."""
    d = lyd.SourceDiagnosis(source_name="X")
    d.final_scores = [20.0, 30.0, 25.0, 38.0, 35.0]
    pats = [pid for pid, _ in d.classify()]
    _check(
        "b1 final_score < 40 連発 → low_score 検出",
        lyd.PATTERN_LOW_SCORE in pats,
        f"got patterns={pats}",
    )


def test_pattern_fetch_dead():
    d = lyd.SourceDiagnosis(source_name="X")
    d.days_observed = 7
    d.days_with_zero_fetch = 5
    pats = [pid for pid, _ in d.classify()]
    _check(
        "b2 days_with_zero_fetch >= 3 → fetch_dead 検出",
        lyd.PATTERN_FETCH_DEAD in pats,
    )


def test_pattern_rank_below_top3():
    d = lyd.SourceDiagnosis(source_name="X")
    d.final_scores = [60.0, 70.0, 55.0, 50.0, 65.0]
    d.selection_reasons[lyd.PATTERN_RANK_BELOW_TOP3] = 5
    pats = [pid for pid, _ in d.classify()]
    _check(
        "b3 score 平均 ≥ 40 + rank_below_top_3 多発 → rank_below_top_3 検出",
        lyd.PATTERN_RANK_BELOW_TOP3 in pats,
    )


def test_pattern_stage1_filtered():
    d = lyd.SourceDiagnosis(source_name="X")
    d.selection_reasons[lyd.PATTERN_STAGE1_FILTERED] = 4
    pats = [pid for pid, _ in d.classify()]
    _check(
        "b4 stage1_filtered 多発 → stage1_filtered 検出",
        lyd.PATTERN_STAGE1_FILTERED in pats,
    )


def test_pattern_cross_page_dedup():
    d = lyd.SourceDiagnosis(source_name="X")
    d.selection_reasons[lyd.PATTERN_CROSS_PAGE_DEDUP] = 6
    pats = [pid for pid, _ in d.classify()]
    _check(
        "b5 cross_page_dedup 多発 → cross_page_dedup 検出",
        lyd.PATTERN_CROSS_PAGE_DEDUP in pats,
    )


def test_pattern_healthy_source_no_match():
    """高 score + 適度に採用されてる source はパターン無マッチ."""
    d = lyd.SourceDiagnosis(source_name="X")
    d.final_scores = [60.0, 65.0, 55.0]
    d.days_observed = 7
    d.days_with_zero_fetch = 0
    d.total_articles_selected = 5
    pats = [pid for pid, _ in d.classify()]
    _check(
        "b6 健全な source → パターン無マッチ",
        pats == [],
        f"got patterns={pats}",
    )


# ---------------------------------------------------------------------------
# (c) Reporting
# ---------------------------------------------------------------------------

def test_markdown_renders_table_header():
    d = lyd.SourceDiagnosis(source_name="Foreign Affairs（CFR）")
    d.total_articles_evaluated = 5
    d.final_scores = [30.0, 35.0, 28.0]
    md = lyd.render_markdown(
        {"Foreign Affairs（CFR）": d},
        start=date(2026, 6, 17), end=date(2026, 6, 23),
    )
    _check(
        "c1 markdown 出力: タイトル + table header + パターン詳細",
        "# Layer-3 Source Diagnosis" in md
        and "| Source | 評価件数" in md
        and "Foreign Affairs（CFR）" in md
        and "low_score" in md,
        f"len={len(md)}",
    )


def test_json_renders_valid_structure():
    d = lyd.SourceDiagnosis(source_name="Test Source")
    d.total_articles_evaluated = 3
    d.total_articles_selected = 1
    d.final_scores = [50.0, 60.0]
    out = lyd.render_json(
        {"Test Source": d},
        start=date(2026, 6, 17), end=date(2026, 6, 23),
    )
    parsed = json.loads(out)
    _check(
        "c2 JSON 出力: range + sources キー、source ごとに必須メタ",
        parsed["range"]["start"] == "2026-06-17"
        and parsed["range"]["end"] == "2026-06-23"
        and "Test Source" in parsed["sources"]
        and parsed["sources"]["Test Source"]["total_articles_evaluated"] == 3,
    )


def test_pattern_filter_only_shows_matching_sources():
    healthy = lyd.SourceDiagnosis(source_name="Healthy")
    healthy.final_scores = [60, 65, 70]
    healthy.total_articles_evaluated = 3
    healthy.total_articles_selected = 2

    broken = lyd.SourceDiagnosis(source_name="Broken")
    broken.final_scores = [20, 25, 30]
    broken.total_articles_evaluated = 3

    md = lyd.render_markdown(
        {"Healthy": healthy, "Broken": broken},
        start=date(2026, 6, 17), end=date(2026, 6, 23),
        pattern_filter=lyd.PATTERN_LOW_SCORE,
    )
    _check(
        "c3 pattern_filter='low_score' で broken のみ表示",
        "Broken" in md and "Healthy |" not in md,
    )


# ---------------------------------------------------------------------------
# (d) CLI entry
# ---------------------------------------------------------------------------

def test_cli_default_dates_no_logs():
    """ログが無い場合でも CLI は exit 0 + 'no matching rows' を返す."""
    import io
    saved = sys.stdout
    sys.stdout = io.StringIO()
    with tempfile.TemporaryDirectory() as td:
        rc = lyd.main([
            "--start", "2099-01-01", "--end", "2099-01-01",
            "--log-dir", td,
        ])
        out = sys.stdout.getvalue()
    sys.stdout = saved
    _check(
        "d1 CLI: ログなし → exit 0 + 'no matching rows'",
        rc == 0 and "no matching rows" in out,
    )


def test_cli_invalid_date_range():
    import io
    saved_err = sys.stderr
    sys.stderr = io.StringIO()
    with tempfile.TemporaryDirectory() as td:
        rc = lyd.main([
            "--start", "2026-06-20", "--end", "2026-06-17",
            "--log-dir", td,
        ])
        err = sys.stderr.getvalue()
    sys.stderr = saved_err
    _check(
        "d2 CLI: end < start → exit 2",
        rc == 2 and "before" in err.lower() or "<" in err,
    )


def test_cli_days_flag():
    """--days で 過去 N 日を自動算出（log なしで動作のみ確認）."""
    import io
    saved = sys.stdout
    sys.stdout = io.StringIO()
    with tempfile.TemporaryDirectory() as td:
        rc = lyd.main([
            "--days", "7",
            "--log-dir", td,
        ])
    sys.stdout = saved
    _check("d3 CLI: --days=7 で exit 0", rc == 0)


def main() -> int:
    print("layer3_diagnosis unit tests (C85 Sub-Step 5b)")
    print()
    print("(a) collect_diagnosis:")
    test_collect_filters_to_layer_3_by_default()
    test_collect_layer_filter_none_includes_all()
    test_collect_source_substring_filter()
    test_collect_handles_missing_log()
    test_collect_multi_day_aggregates()

    print()
    print("(b) パターン判定:")
    test_pattern_low_score()
    test_pattern_fetch_dead()
    test_pattern_rank_below_top3()
    test_pattern_stage1_filtered()
    test_pattern_cross_page_dedup()
    test_pattern_healthy_source_no_match()

    print()
    print("(c) Reporting:")
    test_markdown_renders_table_header()
    test_json_renders_valid_structure()
    test_pattern_filter_only_shows_matching_sources()

    print()
    print("(d) CLI entry:")
    test_cli_default_dates_no_logs()
    test_cli_invalid_date_range()
    test_cli_days_flag()

    print()
    print(f"=== {PASS} passed, {FAIL} failed ===")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
