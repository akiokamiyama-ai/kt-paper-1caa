"""Layer-3 source diagnosis CLI (C85 Sub-Step 5b, Phase B Step 4).

Tribune の layered Stage 2 で「層 3 source は Sonnet 必須として上位扱いに
しているのに、結果として採用 0 件」のような状況の真因を切り分ける運用ツール。

入力
-----

``logs/scores_YYYY-MM-DD.json`` 群を期間指定で読み込み、層 3 source 別に集約。
scores log の各 entry に C85 Sub-Step 5a で追加した以下のフィールドを使う:

- ``layer``                  : 1 / 2 / 3
- ``model``                  : "claude-haiku-4-5" or "claude-sonnet-4-6"
- ``evaluation_mode``        : "sonnet_full" / "haiku_full" / "haiku_prefilter_only"
- ``caller``                 : "page1_master" / "page3" / ...
- ``final_score``            : Stage 3 統合後（None なら未統合）
- ``selected_for_page``      : 採用面（"page1" / "page3.R1" / null）
- ``selection_reason``       : "rank_below_top_3" / "page1_dedup_*" / ...

これらフィールドは shadow mode 7 日後の運用時に充実する。本ツールは scores
log の現行 schema（layered メタなし）にも fallback 動作する。

判定パターン（真因判定マトリックス）
-------------------------------------

1. **評価で落ちる**: final_score < 40 連発 → system prompt 見直し
2. **配置で落ちる**: score ≥ 40 + ``rank_below_top_3`` 連発 → Page1 top_3 拡張
3. **hard_filter**: ``stage1_filtered`` 多発 → description_length 閾値見直し
4. **同日他面で重複**: ``cross_page_dedup`` 多発 → dedup 優先度
5. **取得経路の死活**: articles_fetched=0 連続 → RSS / scraper 確認

CLI
---

::

    python3 -m scripts.analytics.layer3_diagnosis \\
        --start 2026-06-17 --end 2026-06-23

    python3 -m scripts.analytics.layer3_diagnosis \\
        --source "Foreign Affairs（CFR）" --days 30

    python3 -m scripts.analytics.layer3_diagnosis \\
        --pattern rank_below_top_3 --threshold 5 --format json
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
LOG_DIR = PROJECT_ROOT / "logs"


# ---------------------------------------------------------------------------
# Pattern classification
# ---------------------------------------------------------------------------

PATTERN_LOW_SCORE = "low_score"               # final_score < 40
PATTERN_RANK_BELOW_TOP3 = "rank_below_top_3"  # high score but not picked
PATTERN_STAGE1_FILTERED = "stage1_filtered"   # hard_filter で落ちる
PATTERN_CROSS_PAGE_DEDUP = "cross_page_dedup"
PATTERN_FETCH_DEAD = "fetch_dead"             # articles_fetched=0 連続

ALL_PATTERNS = (
    PATTERN_LOW_SCORE,
    PATTERN_RANK_BELOW_TOP3,
    PATTERN_STAGE1_FILTERED,
    PATTERN_CROSS_PAGE_DEDUP,
    PATTERN_FETCH_DEAD,
)

LOW_SCORE_THRESHOLD = 40.0


@dataclass
class SourceDiagnosis:
    """1 source の期間集計（神山さん運用向けの 1 行）."""

    source_name: str
    days_observed: int = 0
    days_fetched: int = 0
    days_with_zero_fetch: int = 0
    total_articles_evaluated: int = 0
    total_articles_selected: int = 0
    final_scores: list[float] = field(default_factory=list)
    selection_reasons: Counter = field(default_factory=Counter)
    selected_for_page: Counter = field(default_factory=Counter)
    callers: Counter = field(default_factory=Counter)
    layers: Counter = field(default_factory=Counter)
    evaluation_modes: Counter = field(default_factory=Counter)

    @property
    def avg_final_score(self) -> float | None:
        if not self.final_scores:
            return None
        return sum(self.final_scores) / len(self.final_scores)

    @property
    def adoption_rate(self) -> float:
        if not self.total_articles_evaluated:
            return 0.0
        return self.total_articles_selected / self.total_articles_evaluated

    def classify(self) -> list[tuple[str, str]]:
        """Return matched patterns with one-line explanations.

        各パターンは ``(pattern_id, human_message)`` のタプル。
        """
        out: list[tuple[str, str]] = []

        # 5. fetch_dead (連続 0 件)
        if self.days_with_zero_fetch >= 3:
            out.append((
                PATTERN_FETCH_DEAD,
                f"articles_fetched=0 が {self.days_with_zero_fetch}/{self.days_observed} 日。"
                f"取得経路の死活確認（RSS / scraper / bot 遮断）"
            ))

        # 1. low_score (final_score < 40 連発)
        if self.final_scores:
            below = sum(1 for s in self.final_scores if s < LOW_SCORE_THRESHOLD)
            if below >= max(3, len(self.final_scores) * 0.5):
                avg = self.avg_final_score
                out.append((
                    PATTERN_LOW_SCORE,
                    f"final_score 平均 {avg:.1f}、< {LOW_SCORE_THRESHOLD} が {below}/{len(self.final_scores)} 件。"
                    f"system prompt の本 source 領域の評価軸見直し検討"
                ))

        # 2. rank_below_top_3 (high score but not picked)
        rbt = self.selection_reasons.get(PATTERN_RANK_BELOW_TOP3, 0)
        if rbt >= 3 and self.avg_final_score and self.avg_final_score >= LOW_SCORE_THRESHOLD:
            out.append((
                PATTERN_RANK_BELOW_TOP3,
                f"score 平均 {self.avg_final_score:.1f} あるが rank_below_top_3 が {rbt} 件。"
                f"Page1 top_3 拡張 or 専用枠検討"
            ))

        # 3. stage1_filtered
        s1 = self.selection_reasons.get(PATTERN_STAGE1_FILTERED, 0)
        if s1 >= 3:
            out.append((
                PATTERN_STAGE1_FILTERED,
                f"stage1_filtered が {s1} 件。description_length / mainstream 閾値見直し"
            ))

        # 4. cross_page_dedup
        cp = self.selection_reasons.get(PATTERN_CROSS_PAGE_DEDUP, 0)
        if cp >= 3:
            out.append((
                PATTERN_CROSS_PAGE_DEDUP,
                f"cross_page_dedup が {cp} 件。dedup 優先度の見直し"
            ))

        return out


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def iter_dates(start: date, end: date):
    cur = start
    while cur <= end:
        yield cur
        cur += timedelta(days=1)


def load_scores_for_day(day: date, *, log_dir: Path = LOG_DIR) -> dict | None:
    """Load logs/scores_YYYY-MM-DD.json or None if missing/corrupt.

    schema は ``{url: entry}`` の dict もしくは ``{"evaluations_by_url": {url: entry}}``
    でラップされた dict を許容する（scripts.selector.stage2.write_scores_log の
    出力形式に追従）。
    """
    path = log_dir / f"scores_{day.isoformat()}.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(data, dict):
        return None
    # write_scores_log 形式の wrapping
    if "evaluations_by_url" in data and isinstance(data["evaluations_by_url"], dict):
        return data["evaluations_by_url"]
    return data


def collect_diagnosis(
    *,
    start: date,
    end: date,
    source_filter: str | None = None,
    layer_filter: int | None = 3,
    log_dir: Path = LOG_DIR,
) -> dict[str, SourceDiagnosis]:
    """Aggregate scores logs over [start, end] into per-source SourceDiagnosis.

    Parameters
    ----------
    source_filter :
        部分一致 substring。``None`` なら全 source。
    layer_filter :
        指定層のみ集計。デフォルト 3（層 3 source 専用）。``None`` で全層。
    """
    diagnoses: dict[str, SourceDiagnosis] = {}
    days_total = 0
    for day in iter_dates(start, end):
        days_total += 1
        entries = load_scores_for_day(day, log_dir=log_dir)
        if entries is None:
            continue
        # その日に観測された source
        seen_sources_today: set[str] = set()
        for url, entry in entries.items():
            if not isinstance(entry, dict):
                continue
            name = entry.get("source_name") or _infer_source_from_entry(entry, url)
            if not name:
                continue
            if source_filter and source_filter not in name:
                continue
            if layer_filter is not None:
                lyr = entry.get("layer")
                if lyr is not None and lyr != layer_filter:
                    continue
            d = diagnoses.setdefault(name, SourceDiagnosis(source_name=name))
            d.total_articles_evaluated += 1
            seen_sources_today.add(name)

            fs = entry.get("final_score")
            if isinstance(fs, (int, float)):
                d.final_scores.append(float(fs))

            sel = entry.get("selected_for_page")
            if sel:
                d.total_articles_selected += 1
                d.selected_for_page[sel] += 1

            reason = entry.get("selection_reason")
            if reason:
                d.selection_reasons[reason] += 1

            caller = entry.get("caller")
            if caller:
                d.callers[caller] += 1
            lyr = entry.get("layer")
            if lyr is not None:
                d.layers[lyr] += 1
            mode = entry.get("evaluation_mode")
            if mode:
                d.evaluation_modes[mode] += 1

        for d in diagnoses.values():
            d.days_observed += 1
            if d.source_name in seen_sources_today:
                d.days_fetched += 1
            else:
                d.days_with_zero_fetch += 1

    return diagnoses


def _infer_source_from_entry(entry: dict, url: str) -> str | None:
    """source_name が entry に無い場合の最低限の fallback (実 schema には残ってる)."""
    return entry.get("source") or None


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def render_markdown(
    diagnoses: dict[str, SourceDiagnosis],
    *,
    start: date,
    end: date,
    pattern_filter: str | None = None,
    threshold: int = 0,
) -> str:
    """神山さん運用向けの markdown table。コピペで note にも使える。"""
    lines: list[str] = [
        f"# Layer-3 Source Diagnosis ({start.isoformat()} → {end.isoformat()})",
        "",
        f"対象 source: {len(diagnoses)} 件",
        "",
        "| Source | 評価件数 | 採用件数 | 採用率 | 平均score | 主要 selection_reason | 判定パターン |",
        "|---|---:|---:|---:|---:|---|---|",
    ]
    sorted_items = sorted(
        diagnoses.items(),
        key=lambda kv: (kv[1].total_articles_selected, kv[1].total_articles_evaluated),
        reverse=True,
    )
    any_row = False
    for name, d in sorted_items:
        patterns = d.classify()
        if pattern_filter:
            patterns = [(pid, msg) for pid, msg in patterns if pid == pattern_filter]
            if not patterns:
                continue
        if threshold and d.total_articles_selected < threshold and not patterns:
            continue
        any_row = True
        avg = d.avg_final_score
        top_reason = (
            d.selection_reasons.most_common(1)[0][0]
            if d.selection_reasons else "—"
        )
        pat_str = (
            "; ".join(f"**{pid}**" for pid, _ in patterns) if patterns else "—"
        )
        lines.append(
            f"| {name} | {d.total_articles_evaluated} | {d.total_articles_selected} | "
            f"{d.adoption_rate * 100:.1f}% | "
            f"{f'{avg:.1f}' if avg is not None else '—'} | "
            f"{top_reason} | {pat_str} |"
        )

    if not any_row:
        lines.append("| (no matching rows) | | | | | | |")

    # 詳細セクション（パターン別の人間用説明）
    lines.append("")
    lines.append("## パターン詳細")
    for name, d in sorted_items:
        patterns = d.classify()
        if pattern_filter:
            patterns = [(pid, msg) for pid, msg in patterns if pid == pattern_filter]
        if not patterns:
            continue
        lines.append(f"\n### {name}")
        for pid, msg in patterns:
            lines.append(f"- **{pid}**: {msg}")

    return "\n".join(lines) + "\n"


def render_json(
    diagnoses: dict[str, SourceDiagnosis],
    *,
    start: date,
    end: date,
    pattern_filter: str | None = None,
    threshold: int = 0,
) -> str:
    out: dict = {
        "range": {"start": start.isoformat(), "end": end.isoformat()},
        "sources": {},
    }
    for name, d in diagnoses.items():
        patterns = d.classify()
        if pattern_filter:
            patterns = [(pid, msg) for pid, msg in patterns if pid == pattern_filter]
            if not patterns:
                continue
        if threshold and d.total_articles_selected < threshold and not patterns:
            continue
        out["sources"][name] = {
            "days_observed": d.days_observed,
            "days_fetched": d.days_fetched,
            "days_with_zero_fetch": d.days_with_zero_fetch,
            "total_articles_evaluated": d.total_articles_evaluated,
            "total_articles_selected": d.total_articles_selected,
            "adoption_rate": round(d.adoption_rate, 4),
            "avg_final_score": (
                round(d.avg_final_score, 2) if d.avg_final_score is not None else None
            ),
            "final_scores": [round(s, 2) for s in d.final_scores],
            "selection_reasons": dict(d.selection_reasons.most_common()),
            "selected_for_page": dict(d.selected_for_page.most_common()),
            "callers": dict(d.callers.most_common()),
            "layers": dict(d.layers.most_common()),
            "evaluation_modes": dict(d.evaluation_modes.most_common()),
            "patterns": [{"id": pid, "message": msg} for pid, msg in patterns],
        }
    return json.dumps(out, ensure_ascii=False, indent=2) + "\n"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Layer-3 source diagnosis from scores_*.json logs"
    )
    parser.add_argument("--start", help="開始日 YYYY-MM-DD")
    parser.add_argument("--end", help="終了日 YYYY-MM-DD")
    parser.add_argument("--days", type=int, default=None,
                        help="今日から N 日遡る（--start/--end の代替）")
    parser.add_argument("--source", default=None,
                        help="source 部分一致フィルタ（例 'Foreign Affairs'）")
    parser.add_argument("--layer", type=int, default=3,
                        help="層フィルタ（デフォルト 3、層 3 source のみ）")
    parser.add_argument("--pattern", choices=ALL_PATTERNS, default=None,
                        help="判定パターンで絞り込み")
    parser.add_argument("--threshold", type=int, default=0,
                        help="採用件数 < threshold かつ パターン無マッチの source を非表示")
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown",
                        help="出力形式（デフォルト markdown）")
    parser.add_argument("--log-dir", type=Path, default=LOG_DIR,
                        help="logs/ ディレクトリ override（test 用）")
    args = parser.parse_args(argv)

    # 期間決定
    if args.days is not None:
        end = date.today()
        start = end - timedelta(days=args.days - 1)
    elif args.start and args.end:
        try:
            start = date.fromisoformat(args.start)
            end = date.fromisoformat(args.end)
        except ValueError as e:
            print(f"error: invalid date: {e}", file=sys.stderr)
            return 2
    else:
        # デフォルト: 過去 7 日
        end = date.today()
        start = end - timedelta(days=6)

    if end < start:
        print(f"error: --end {end} < --start {start}", file=sys.stderr)
        return 2

    diagnoses = collect_diagnosis(
        start=start, end=end,
        source_filter=args.source,
        layer_filter=args.layer,
        log_dir=args.log_dir,
    )

    if args.format == "json":
        out = render_json(
            diagnoses, start=start, end=end,
            pattern_filter=args.pattern, threshold=args.threshold,
        )
    else:
        out = render_markdown(
            diagnoses, start=start, end=end,
            pattern_filter=args.pattern, threshold=args.threshold,
        )
    sys.stdout.write(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
