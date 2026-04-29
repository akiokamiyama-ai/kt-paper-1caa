"""Daily LLM usage tracking and cost cap.

The second-line defense against runaway LLM costs (the first line is the
month-budget cap set in the Anthropic Console — see docs/security_review_v1.md
§6.3). This module records every Anthropic API call and refuses further
calls once the daily limits are reached.

Two caps are enforced:

* ``DAILY_COST_CAP_USD`` — total estimated cost in USD. Conservative cushion
  above the design's predicted 0.05–0.10 USD/day (aesthetics_design_v1.md
  §4.2).
* ``DAILY_CALLS_CAP`` — count of API calls. Catches "infinite loop" failure
  modes that token caps alone would miss (e.g. if every call is empty).

Usage log structure (``logs/llm_usage_YYYY-MM-DD.json``)::

    {
      "date": "2026-04-27",
      "calls": [
        {
          "ts": "2026-04-27T06:30:00",
          "model": "claude-sonnet-4-6",
          "input_tokens": 4521,
          "output_tokens": 312,
          "cost_usd": 0.018231
        },
        ...
      ],
      "totals": {
        "calls": 12,
        "input_tokens": 50_244,
        "output_tokens": 3_891,
        "cost_usd": 0.209091
      }
    }

Pricing constants need to be revisited when Anthropic changes their tariff
or a new model is adopted.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

LOG_DIR = Path(__file__).resolve().parent.parent.parent / "logs"

# Caps. Override at runtime by editing this file (intentionally not exposed
# via env vars — these are durable safety bounds, not per-run knobs).
DAILY_COST_CAP_USD = 0.50   # design predicts 0.05-0.10/day; 5x cushion
DAILY_CALLS_CAP = 200        # design predicts ~10-20 calls/day; 10x cushion

# Model pricing (USD per 1M tokens). Snapshot of 2026-04 published rates;
# update when Anthropic revises pricing or a new model is adopted.
#
# cache_write_per_mtok / cache_read_per_mtok cover the 5-minute ephemeral
# prompt caching used by Stage 2. Anthropic charges:
#   cache write  = 1.25× base input rate (5min TTL)
#   cache read   = 0.10× base input rate
# Models that don't surface cache token counts back to the SDK still work —
# their cache_*_per_mtok entries simply go unused.
MODEL_PRICING: dict[str, dict[str, float]] = {
    "claude-sonnet-4-6": {
        "input_per_mtok": 3.0,
        "output_per_mtok": 15.0,
        "cache_write_per_mtok": 3.75,
        "cache_read_per_mtok": 0.30,
    },
    "claude-opus-4-7": {
        "input_per_mtok": 15.0,
        "output_per_mtok": 75.0,
        "cache_write_per_mtok": 18.75,
        "cache_read_per_mtok": 1.50,
    },
    "claude-haiku-4-5": {
        "input_per_mtok": 0.80,
        "output_per_mtok": 4.0,
        "cache_write_per_mtok": 1.0,
        "cache_read_per_mtok": 0.08,
    },
}


@dataclass
class CapStatus:
    ok: bool
    reason: str
    today_calls: int
    today_cost_usd: float


def _log_path(d: date) -> Path:
    return LOG_DIR / f"llm_usage_{d.isoformat()}.json"


def _empty_log(d: date) -> dict:
    return {
        "date": d.isoformat(),
        "calls": [],
        "totals": {"calls": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0},
    }


def _load_today(d: date) -> dict:
    path = _log_path(d)
    if not path.exists():
        return _empty_log(d)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        # Corrupt log — start fresh rather than crash. The corruption itself
        # is a signal worth investigating, but losing today's count to that
        # is preferable to halting the pipeline mid-run.
        return _empty_log(d)
    # Defensive: ensure structure invariants.
    data.setdefault("date", d.isoformat())
    data.setdefault("calls", [])
    data.setdefault("totals", _empty_log(d)["totals"])
    return data


def estimate_cost(
    model: str,
    input_tokens: int,
    output_tokens: int,
    *,
    cache_creation_tokens: int = 0,
    cache_read_tokens: int = 0,
) -> float:
    """Return the estimated cost in USD for one call. Unknown models cost 0.

    ``input_tokens`` is the count of *non-cached* input tokens (i.e. what
    the Anthropic SDK reports as ``usage.input_tokens``). Cache tokens are
    accounted for separately at their reduced rate. Existing callers that
    don't pass cache counts default to 0 and behave exactly as before.
    """
    rates = MODEL_PRICING.get(model)
    if not rates:
        return 0.0
    return (
        (input_tokens / 1_000_000) * rates["input_per_mtok"]
        + (output_tokens / 1_000_000) * rates["output_per_mtok"]
        + (cache_creation_tokens / 1_000_000) * rates.get("cache_write_per_mtok", 0.0)
        + (cache_read_tokens / 1_000_000) * rates.get("cache_read_per_mtok", 0.0)
    )


def check_caps(today: date | None = None) -> CapStatus:
    """Return the current usage state vs caps.

    Phase 2 callers should consult this *before* each LLM call. ``ok=False``
    means the daily cap has been reached and further calls must be skipped.
    """
    d = today or date.today()
    data = _load_today(d)
    totals = data["totals"]
    calls = totals.get("calls", 0)
    cost = totals.get("cost_usd", 0.0)
    if calls >= DAILY_CALLS_CAP:
        return CapStatus(
            ok=False,
            reason=f"daily call cap reached ({calls} >= {DAILY_CALLS_CAP})",
            today_calls=calls,
            today_cost_usd=cost,
        )
    if cost >= DAILY_COST_CAP_USD:
        return CapStatus(
            ok=False,
            reason=f"daily cost cap reached (${cost:.4f} >= ${DAILY_COST_CAP_USD})",
            today_calls=calls,
            today_cost_usd=cost,
        )
    return CapStatus(ok=True, reason="under caps", today_calls=calls, today_cost_usd=cost)


def record_call(
    model: str,
    input_tokens: int,
    output_tokens: int,
    today: date | None = None,
    *,
    cache_creation_tokens: int = 0,
    cache_read_tokens: int = 0,
) -> dict:
    """Append one call's usage to today's log and return updated totals.

    Cache token fields are keyword-only with default 0, so existing callers
    keep working unchanged. Stage 2 passes them so the cost estimate reflects
    Anthropic's tiered cache pricing.
    """
    d = today or date.today()
    data = _load_today(d)
    cost = estimate_cost(
        model,
        input_tokens,
        output_tokens,
        cache_creation_tokens=cache_creation_tokens,
        cache_read_tokens=cache_read_tokens,
    )
    entry = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "model": model,
        "input_tokens": int(input_tokens),
        "output_tokens": int(output_tokens),
        "cache_creation_tokens": int(cache_creation_tokens),
        "cache_read_tokens": int(cache_read_tokens),
        "cost_usd": round(cost, 6),
    }
    data["calls"].append(entry)
    t = data["totals"]
    t["calls"] = t.get("calls", 0) + 1
    t["input_tokens"] = t.get("input_tokens", 0) + int(input_tokens)
    t["output_tokens"] = t.get("output_tokens", 0) + int(output_tokens)
    t["cache_creation_tokens"] = (
        t.get("cache_creation_tokens", 0) + int(cache_creation_tokens)
    )
    t["cache_read_tokens"] = t.get("cache_read_tokens", 0) + int(cache_read_tokens)
    t["cost_usd"] = round(t.get("cost_usd", 0.0) + cost, 6)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    _log_path(d).write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return t


def daily_summary(today: date | None = None) -> dict:
    """Return today's totals (or zeroed totals if no log yet)."""
    d = today or date.today()
    return _load_today(d)["totals"]
