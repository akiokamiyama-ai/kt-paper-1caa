"""過去日論考の参照キャッシュ（Phase 3, 2026-05-23）.

仕様 §4.5：月-金の論考生成時、当週の過去日論考を context として LLM に
渡す（同主軸記事への異角度論考の重複・矛盾を避けるため）。土曜の応答
生成でも 6 日分の論考サマリを参照する。

archive HTML から逆抽出するより堅牢な、週単位キャッシュとして
``logs/page1_v3_history.json`` に保存する。
"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import date
from pathlib import Path
from typing import Any

from .monthly_pivotal import WeekContext

DEFAULT_HISTORY_PATH = (
    Path(__file__).resolve().parent.parent.parent / "logs" / "page1_v3_history.json"
)


def _load_raw(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _save_raw(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def save_essay(
    week: WeekContext,
    target_date: date,
    essay: Any,
    *,
    history_path: Path | None = None,
) -> None:
    """1 日分の essay を週単位キャッシュに保存. 同日上書き OK.

    ``essay`` は EssayResult dataclass（or asdict 可能な任意の dataclass）.
    モジュール循環を避けるため型は ``Any`` 受け。
    """
    path = history_path or DEFAULT_HISTORY_PATH
    data = _load_raw(path)
    key = week.history_key()
    week_block = data.setdefault(key, {
        "week_label": week.week_label,
        "theme": week.theme,
        "period": [week.period[0].isoformat(), week.period[1].isoformat()],
        "entries": [],
    })
    entries: list[dict] = week_block["entries"]
    payload = {
        "date": target_date.isoformat(),
        "day_label": week.day_label,
        "angle_key": week.angle_key,
        "angle_label_jp": week.angle_label_jp,
        "essay": asdict(essay) if hasattr(essay, "__dataclass_fields__") else dict(essay),
    }
    # 同日エントリは差し替え（再ラン耐性）
    week_block["entries"] = [e for e in entries if e.get("date") != target_date.isoformat()]
    week_block["entries"].append(payload)
    week_block["entries"].sort(key=lambda e: e.get("date", ""))
    _save_raw(path, data)


def load_week_essays(
    week: WeekContext,
    *,
    history_path: Path | None = None,
) -> list[dict]:
    """週内の保存済み essay を日付順で返す。未保存 / 欠落は空リスト.

    返り値は dict のリスト（EssayResult を import すると循環するため）。
    各 dict は ``date / day_label / angle_key / angle_label_jp / essay (dict)``。
    """
    path = history_path or DEFAULT_HISTORY_PATH
    data = _load_raw(path)
    week_block = data.get(week.history_key())
    if not week_block:
        return []
    entries = week_block.get("entries") or []
    return sorted(entries, key=lambda e: e.get("date", ""))
