"""shadow 評価ログの読み書き (C211, 2026-10-05).

``logs/shadow_eval_<date>.json``::

    {"date": "2026-10-06",
     "entries": [
       {"url": ..., "scorer": "jev", "scores": {...}, "confidence": {...},
        "probabilities": {...}, "cost_usd": ..., "elapsed_ms": ..., "error": null,
        "baseline": {"美意識1": 6, ...},      # 同じ記事の本番 Sonnet スコア
        "caller": "page3", "recorded_at": ...}
     ]}

同一 ``(url, scorer)`` は **upsert**（C185 と同じ思想で二重記録を作らない）。
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

LOG_DIR = Path(__file__).resolve().parents[2] / "logs"


def log_path(d: date | None = None) -> Path:
    from scripts.lib.jst import jst_today
    return LOG_DIR / f"shadow_eval_{(d or jst_today()).isoformat()}.json"


def load(path: Path | None = None) -> dict:
    p = path or log_path()
    if not p.exists():
        return {"date": p.stem.replace("shadow_eval_", ""), "entries": []}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        print(f"[shadow/store] load failed ({type(e).__name__}), treating as empty",
              file=sys.stderr)
        return {"date": p.stem.replace("shadow_eval_", ""), "entries": []}
    if not isinstance(data, dict) or not isinstance(data.get("entries"), list):
        return {"date": p.stem.replace("shadow_eval_", ""), "entries": []}
    return data


def save(data: dict, path: Path | None = None) -> None:
    p = path or log_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def record(entries: list[dict], *, path: Path | None = None) -> int:
    """エントリを upsert して、書いた件数を返す。失敗しても例外は投げない."""
    if not entries:
        return 0
    try:
        p = path or log_path()
        data = load(p)
        index = {(e.get("url"), e.get("scorer")): i
                 for i, e in enumerate(data["entries"])}
        for e in entries:
            k = (e.get("url"), e.get("scorer"))
            if k in index:
                data["entries"][index[k]] = e
            else:
                index[k] = len(data["entries"])
                data["entries"].append(e)
        save(data, p)
        return len(entries)
    except Exception as e:  # noqa: BLE001 — 観測で紙面を落とさない
        print(f"[shadow/store] record failed (non-fatal): {type(e).__name__}: {e}",
              file=sys.stderr)
        return 0


def load_range(days: int, *, until: date | None = None) -> list[dict]:
    """直近 ``days`` 日ぶんのエントリをまとめて返す（比較用）."""
    from datetime import timedelta

    from scripts.lib.jst import jst_today

    end = until or jst_today()
    out: list[dict] = []
    for i in range(days):
        d = end - timedelta(days=i)
        p = log_path(d)
        if not p.exists():
            continue
        for e in load(p)["entries"]:
            e = dict(e)
            e.setdefault("date", d.isoformat())
            out.append(e)
    return out
