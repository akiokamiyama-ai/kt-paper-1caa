"""LLM コストを tag 別 / 日別に集計表示する（Phase A, 2026-06-01）.

``logs/llm_usage_YYYY-MM-DD.json`` を走査して、各 tag のコスト・呼び出し回数
を集計する。Phase A の tag 命名整理 (`stage2.batch`, `page2.headlines_summary`
等) で面別 + 種別の breakdown が読みやすくなった。

GHA artifact 経由のログ取得補助も兼ねる（注釈参照）。

使用例
------

最近 7 日の集計（プロジェクト logs/ にあるファイルを舐める）::

    python3 -m scripts.tools.llm_cost_breakdown --days 7

特定日::

    python3 -m scripts.tools.llm_cost_breakdown --date 2026-06-01

任意ディレクトリのログ集計（GHA artifact を展開した先など）::

    python3 -m scripts.tools.llm_cost_breakdown --log-dir /tmp/gha-logs --days 30

GHA artifact 取得の補助コマンド（参考、別途実行）::

    gh run list --workflow daily.yml --limit 30 --json databaseId,createdAt \\
        | jq -r '.[] | "\\(.databaseId) \\(.createdAt)"' \\
        | while read id ts; do gh run download $id -n "audit-logs-$(echo $ts | cut -c1-10)" -D /tmp/gha-logs/$id 2>/dev/null; done

集計結果の読み方：
- ``stage2.batch`` がコスト構造の支配的因子（Sprint 8 時点で 90% 超）。
  page 非依存のフラット evaluation なので「面別コスト」の解像度は本質的に
  上げられない。「Stage 2 を per-page に分割」は tokens が面数倍になる
  ため非推奨。低コスト化は Stage 2 内の最適化（batch_size 調整 / cache 拡張 /
  prompt 短縮）で攻める。
- ``page*.*`` 系 tag は面別生成 LLM call の breakdown を可視化する。
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_LOG_DIR = PROJECT_ROOT / "logs"


def _iter_log_files(log_dir: Path, dates: list[date]) -> list[tuple[date, Path]]:
    found = []
    for d in dates:
        p = log_dir / f"llm_usage_{d.isoformat()}.json"
        if p.exists():
            found.append((d, p))
    return found


def _date_range(end: date, days_back: int) -> list[date]:
    return [end - timedelta(days=i) for i in range(days_back - 1, -1, -1)]


def _aggregate(files: list[tuple[date, Path]]) -> dict:
    by_tag: dict[str, dict] = defaultdict(
        lambda: {"calls": 0, "cost_usd": 0.0, "input_tokens": 0, "output_tokens": 0}
    )
    by_date: dict[date, dict] = defaultdict(
        lambda: {"calls": 0, "cost_usd": 0.0}
    )
    grand = {"calls": 0, "cost_usd": 0.0, "input_tokens": 0, "output_tokens": 0}
    for d, path in files:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        for c in data.get("calls", []):
            tag = c.get("tag") or "(untagged)"
            cost = float(c.get("cost_usd") or 0.0)
            in_tok = int(c.get("input_tokens") or 0)
            out_tok = int(c.get("output_tokens") or 0)
            by_tag[tag]["calls"] += 1
            by_tag[tag]["cost_usd"] += cost
            by_tag[tag]["input_tokens"] += in_tok
            by_tag[tag]["output_tokens"] += out_tok
            by_date[d]["calls"] += 1
            by_date[d]["cost_usd"] += cost
            grand["calls"] += 1
            grand["cost_usd"] += cost
            grand["input_tokens"] += in_tok
            grand["output_tokens"] += out_tok
    return {"by_tag": dict(by_tag), "by_date": dict(by_date), "grand": grand}


def _print_report(period_label: str, agg: dict) -> None:
    grand = agg["grand"]
    print(f"=== LLM cost breakdown: {period_label} ===")
    print()
    if grand["calls"] == 0:
        print("  (該当ログなし)")
        return
    print(f"  Total: ${grand['cost_usd']:.4f} / {grand['calls']} calls "
          f"(in {grand['input_tokens']:,} tok / out {grand['output_tokens']:,} tok)")
    print()
    print("  Tag breakdown (cost 降順):")
    sorted_tags = sorted(
        agg["by_tag"].items(), key=lambda kv: kv[1]["cost_usd"], reverse=True,
    )
    for tag, st in sorted_tags:
        share = st["cost_usd"] / grand["cost_usd"] * 100 if grand["cost_usd"] > 0 else 0
        print(f"    {tag:36s}  ${st['cost_usd']:8.4f}  {share:5.1f}%  "
              f"({st['calls']:3d} calls, in {st['input_tokens']:>7,} / "
              f"out {st['output_tokens']:>6,})")
    print()
    by_date = sorted(agg["by_date"].items())
    if len(by_date) > 1:
        print("  Date breakdown:")
        for d, st in by_date:
            print(f"    {d.isoformat()}  ${st['cost_usd']:8.4f}  ({st['calls']:3d} calls)")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="llm_cost_breakdown",
        description="Tribune LLM コストを tag 別 / 日別に集計表示する (Phase A)",
    )
    p.add_argument("--days", type=int, default=7,
                   help="今日（指定 --date がない場合）から遡る日数 (default: 7)")
    p.add_argument("--date", type=str,
                   help="単一日 (YYYY-MM-DD) を対象に集計")
    p.add_argument("--log-dir", type=str,
                   help=f"ログディレクトリ (default: {DEFAULT_LOG_DIR})")
    args = p.parse_args(argv)

    log_dir = Path(args.log_dir) if args.log_dir else DEFAULT_LOG_DIR
    if not log_dir.exists():
        print(f"[error] ログディレクトリ {log_dir} が存在しません", file=sys.stderr)
        return 1

    if args.date:
        try:
            single = date.fromisoformat(args.date)
        except ValueError:
            print(f"[error] --date {args.date!r} 不正、ISO 形式 (YYYY-MM-DD) を使ってください",
                  file=sys.stderr)
            return 1
        dates = [single]
        label = single.isoformat()
    else:
        # 当日が JST 切替前後のことがあるが、ローカルマシン today を基準でよい。
        from datetime import datetime as _dt
        today = _dt.now().date()
        dates = _date_range(today, max(1, args.days))
        label = f"{dates[0].isoformat()}〜{dates[-1].isoformat()} ({args.days} days)"

    files = _iter_log_files(log_dir, dates)
    if not files:
        print(f"=== LLM cost breakdown: {label} ===")
        print(f"\n  log_dir={log_dir} に該当ログなし")
        return 0

    agg = _aggregate(files)
    _print_report(label, agg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
