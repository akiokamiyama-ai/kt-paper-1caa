"""Stage 3: Score integration.

Reads the per-article aesthetic scores produced by Stage 1 (machine) and
Stage 2 (LLM), applies the design weights from
``docs/aesthetics_design_v1.md`` §3.1, and writes a single ``final_score``
back into ``logs/scores_YYYY-MM-DD.json``.

Formula
-------

    weighted_sum = Σ (aesthetic_i × weight_i × learning_adj_i)
    base_score   = weighted_sum / 10           # weights sum to 100; aesthetic on 0-10
    final_score  = base_score + penalty        # 美意識4 penalty (0 / -3 / -5)

Aesthetic 2 normalization
-------------------------

Stage 1 records the raw machine score 0/3/5 in ``美意識2_machine``. For
weight calculation we lift it onto the 0-10 scale used by every other
aesthetic so the §3.1 weight (27) can land its full contribution:

    raw 0 → 0     mainstream=true
    raw 3 → 6     mainstream=unknown
    raw 5 → 10    mainstream=false

The raw value is preserved untouched in the log entry. If the raw value
is missing or out of range, we fall back to 6 (unknown-equivalent) and
add ``missing_aesthetic_2_warning: true`` to the entry.

Public API
----------

* ``compute_final_score(entry, *, learning_adj=None) -> tuple[float, bool]``
* ``integrate_scores(entries, *, learning_adj=None) -> int``
* ``update_log_file(log_path=None, *, dry_run=False, learning_adj=None)``
* ``main(argv)`` — ``python3 -m scripts.selector.stage3 [--date ...] [--dry-run]``

Phase 2 Sprint 1 scope
----------------------

* Learning adjustment factors are all 1.0. Sprint 3 will introduce
  ±10 % perturbations from feedback signals.
* The 第2面 (page 2) special weighting from §3.3 is **not** implemented
  here — it will live alongside Stage 4 territory routing.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
LOG_DIR = PROJECT_ROOT / "logs"

# §3.1 base weights; sum = 100. The keys mirror the field names used in
# logs/scores_*.json so we can index entries by ``BASE_WEIGHTS.keys()``.
BASE_WEIGHTS: dict[str, int] = {
    "美意識1": 18,
    "美意識2": 27,
    "美意識3": 27,
    "美意識5": 9,
    "美意識6": 9,
    "美意識8": 10,
}

# Stage 1's raw machine score (0/3/5) lifted onto the 0-10 scale so its
# §3.1 weight (27) lands its full contribution.
AESTHETIC2_RAW_TO_NORM: dict[int, int] = {0: 0, 3: 6, 5: 10}
DEFAULT_AESTHETIC2_NORM = 6  # used when the machine value is missing/null/unknown

# LLM-judged aesthetics (Stage 2 fills these as 0-10 integers).
LLM_AESTHETIC_KEYS: tuple[str, ...] = (
    "美意識1", "美意識3", "美意識5", "美意識6", "美意識8",
)

# Default learning adjustments; Sprint 3 will perturb these per-aesthetic.
DEFAULT_LEARNING_ADJUSTMENTS: dict[str, float] = {k: 1.0 for k in BASE_WEIGHTS}


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class Stage3Result:
    log_path: Path
    updated_count: int
    missing_aesthetic_2_count: int = 0
    score_distribution: dict[str, float] = field(default_factory=dict)
    entries: dict[str, dict] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _normalize_aesthetic2(raw: Any) -> tuple[int, bool]:
    """Map raw 0/3/5 → 0/6/10, returning ``(value, missing_flag)``.

    ``missing_flag`` is True when the raw input is null, non-numeric, or
    not in the allowed {0, 3, 5} set.
    """
    if raw is None:
        return DEFAULT_AESTHETIC2_NORM, True
    try:
        raw_int = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_AESTHETIC2_NORM, True
    if raw_int in AESTHETIC2_RAW_TO_NORM:
        return AESTHETIC2_RAW_TO_NORM[raw_int], False
    return DEFAULT_AESTHETIC2_NORM, True


def _coerce_score(v: Any) -> int:
    try:
        x = int(v)
    except (TypeError, ValueError):
        return 0
    if x < 0:
        return 0
    if x > 10:
        return 10
    return x


def compute_final_score(
    entry: dict,
    *,
    learning_adj: dict[str, float] | None = None,
) -> tuple[float, bool]:
    """Compute final_score for one log entry.

    Parameters
    ----------
    entry :
        A dict with keys ``美意識1`` ``美意識3`` ``美意識5`` ``美意識6`` ``美意識8``
        (each 0-10), ``美意識2_machine`` (raw 0/3/5 or null), and
        ``美意識4_penalty`` (0 / -3 / -5). Missing keys default to 0 / None.
    learning_adj :
        Per-aesthetic multiplicative adjustment. Defaults to all 1.0.

    Returns
    -------
    (final_score, missing_aesthetic_2)
    """
    adj = learning_adj or DEFAULT_LEARNING_ADJUSTMENTS

    weighted_sum = 0.0
    for key in LLM_AESTHETIC_KEYS:
        score = _coerce_score(entry.get(key, 0))
        weighted_sum += score * BASE_WEIGHTS[key] * adj.get(key, 1.0)

    raw2 = entry.get("美意識2_machine")
    norm2, missing = _normalize_aesthetic2(raw2)
    weighted_sum += norm2 * BASE_WEIGHTS["美意識2"] * adj.get("美意識2", 1.0)

    base_score = weighted_sum / 10.0

    try:
        penalty = float(entry.get("美意識4_penalty", 0) or 0)
    except (TypeError, ValueError):
        penalty = 0.0

    final = round(base_score + penalty, 2)
    return final, missing


def integrate_scores(
    entries: dict[str, dict],
    *,
    learning_adj: dict[str, float] | None = None,
) -> tuple[int, int]:
    """In-place: write ``final_score`` (and warning flag) into each entry.

    Returns ``(updated_count, missing_aesthetic_2_count)``.
    """
    updated = 0
    missing_count = 0
    for _url, entry in entries.items():
        final, missing = compute_final_score(entry, learning_adj=learning_adj)
        entry["final_score"] = final
        if missing:
            entry["missing_aesthetic_2_warning"] = True
            missing_count += 1
        elif "missing_aesthetic_2_warning" in entry:
            # A previous run flagged it but data is now valid — clean up.
            del entry["missing_aesthetic_2_warning"]
        updated += 1
    return updated, missing_count


# ---------------------------------------------------------------------------
# Log file IO
# ---------------------------------------------------------------------------

def _scores_log_path(d: date | None = None) -> Path:
    return LOG_DIR / f"scores_{(d or date.today()).isoformat()}.json"


def update_log_file(
    log_path: Path | None = None,
    *,
    dry_run: bool = False,
    learning_adj: dict[str, float] | None = None,
) -> Stage3Result:
    """Read scores_*.json, integrate, write back. Idempotent."""
    if log_path is None:
        log_path = _scores_log_path()
    if not log_path.exists():
        raise FileNotFoundError(f"scores log not found: {log_path}")

    data = json.loads(log_path.read_text(encoding="utf-8"))
    entries = data.get("evaluations", {})
    if not isinstance(entries, dict):
        raise ValueError(
            f"unexpected log shape: 'evaluations' is {type(entries).__name__}, "
            "expected dict"
        )

    print(
        f"Updating final_score for {len(entries)} articles in {log_path}",
        file=sys.stderr,
    )

    updated, missing_count = integrate_scores(entries, learning_adj=learning_adj)

    scores = [
        e["final_score"] for e in entries.values()
        if isinstance(e.get("final_score"), (int, float))
    ]
    distribution: dict[str, float] = {}
    if scores:
        distribution = {
            "count": len(scores),
            "min": round(min(scores), 2),
            "max": round(max(scores), 2),
            "mean": round(statistics.mean(scores), 2),
            "median": round(statistics.median(scores), 2),
        }

    if not dry_run:
        log_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    return Stage3Result(
        log_path=log_path,
        updated_count=updated,
        missing_aesthetic_2_count=missing_count,
        score_distribution=distribution,
        entries=entries,
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="stage3",
        description="Stage 3 score integration (Phase 2 Sprint 1)",
    )
    p.add_argument(
        "--date",
        help="ISO date (YYYY-MM-DD) selecting which scores log to update; "
        "defaults to today",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="compute scores but do not write the file back",
    )
    p.add_argument(
        "--show",
        type=int,
        default=10,
        help="print the top-N articles by final_score (0 disables)",
    )
    args = p.parse_args(argv)

    if args.date:
        try:
            d = date.fromisoformat(args.date)
        except ValueError:
            print(f"invalid --date {args.date!r}, expected YYYY-MM-DD", file=sys.stderr)
            return 1
        log_path = _scores_log_path(d)
    else:
        log_path = _scores_log_path()

    if not log_path.exists():
        print(f"No scores log at {log_path}", file=sys.stderr)
        return 1

    result = update_log_file(log_path, dry_run=args.dry_run)

    print()
    print("=== Stage 3 results ===")
    print(f"  log:                   {result.log_path}")
    print(f"  updated entries:       {result.updated_count}")
    print(f"  missing 美意識2 flags:  {result.missing_aesthetic_2_count}")
    if result.score_distribution:
        d = result.score_distribution
        print(
            f"  final_score min/median/mean/max: "
            f"{d['min']:.2f} / {d['median']:.2f} / {d['mean']:.2f} / {d['max']:.2f}"
        )
    if args.dry_run:
        print("  (dry-run; file not written)")

    if args.show > 0 and result.entries:
        ranked = sorted(
            result.entries.items(),
            key=lambda kv: kv[1].get("final_score", 0.0),
            reverse=True,
        )
        n = min(args.show, len(ranked))
        print()
        print(f"  top {n} by final_score:")
        for i, (url, entry) in enumerate(ranked[:n], 1):
            score = entry.get("final_score", 0.0)
            warn = " [missing_a2]" if entry.get("missing_aesthetic_2_warning") else ""
            print(f"    {i:2d}. {score:6.2f}  {url[:70]}{warn}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
