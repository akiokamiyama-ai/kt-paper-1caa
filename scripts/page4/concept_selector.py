"""Select today's concept for Page IV column.

Reads data/concepts.yaml (52 concepts), excludes those displayed in the
past EXCLUSION_DAYS (60), and picks one at random. Records the selection
in logs/concept_history.json.

Pool exhaustion fallback: if every concept has been displayed in the
window, reuse the **oldest** displayed concept (warning logged).
"""

from __future__ import annotations

import json
import random
import sys
from datetime import date
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_PATH = PROJECT_ROOT / "data" / "concepts.yaml"
HISTORY_PATH = PROJECT_ROOT / "logs" / "concept_history.json"

# 60 日以内に表示済の概念は除外。約 2 ヶ月の重複回避ウィンドウ。
EXCLUSION_DAYS: int = 60


def load_concepts(*, path: Path | None = None) -> list[dict]:
    """Load and return concepts.yaml as a list of dicts."""
    p = path or DATA_PATH
    with open(p, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, list):
        raise ValueError(f"concepts.yaml root must be a list, got {type(data).__name__}")
    return data


def load_history(*, path: Path | None = None) -> dict:
    """Load logs/concept_history.json. Returns ``{"history": []}`` if absent."""
    p = path or HISTORY_PATH
    if not p.exists():
        return {"history": []}
    with open(p, encoding="utf-8") as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError:
            return {"history": []}
    if "history" not in data or not isinstance(data["history"], list):
        return {"history": []}
    return data


def save_history(data: dict, *, path: Path | None = None) -> None:
    p = path or HISTORY_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _excluded_ids(history: dict, today: date, exclusion_days: int) -> set[str]:
    """Return the set of concept_ids displayed within the past exclusion_days."""
    cutoff_ord = today.toordinal() - exclusion_days
    excluded: set[str] = set()
    for entry in history.get("history", []):
        d_str = entry.get("displayed_on", "")
        try:
            d = date.fromisoformat(d_str)
        except (ValueError, TypeError):
            continue
        if d.toordinal() >= cutoff_ord:
            cid = entry.get("concept_id")
            if cid:
                excluded.add(cid)
    return excluded


def select_concept_for_today(
    *,
    today: date | None = None,
    concepts: list[dict] | None = None,
    history: dict | None = None,
    persist: bool = True,
    rng: random.Random | None = None,
    exclusion_days: int = EXCLUSION_DAYS,
) -> dict:
    """Select today's concept; record to history; return concept dict.

    Determinism is intentionally avoided — random.choice on the candidate
    pool keeps the morning surprise. To reproduce a selection in tests,
    pass an explicit ``rng=random.Random(seed)``.
    """
    if today is None:
        today = date.today()
    if concepts is None:
        concepts = load_concepts()
    if history is None:
        history = load_history()
    if rng is None:
        rng = random.Random()

    excluded = _excluded_ids(history, today, exclusion_days)
    candidates = [c for c in concepts if c["id"] not in excluded]

    if not candidates:
        # Pool exhausted — reuse the oldest displayed concept.
        print(
            f"[concept] WARN: all {len(concepts)} concepts displayed in past "
            f"{exclusion_days} days. Reusing the oldest.",
            file=sys.stderr,
        )
        sorted_entries = sorted(
            history.get("history", []),
            key=lambda e: e.get("displayed_on", ""),
        )
        oldest_id = sorted_entries[0]["concept_id"] if sorted_entries else None
        candidates = [c for c in concepts if c["id"] == oldest_id]
        if not candidates:
            # Ultimate fallback: pick anything.
            candidates = list(concepts)

    selected = rng.choice(candidates)

    if persist:
        history.setdefault("history", []).append({
            "concept_id": selected["id"],
            "name_ja": selected["name_ja"],
            "displayed_on": today.isoformat(),
        })
        save_history(history)

    return selected
