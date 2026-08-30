"""Select today's concept for Page IV column.

Reads data/concepts.yaml (52 concepts), excludes those displayed in the
past EXCLUSION_DAYS (60), and picks one at random. Records the selection
in logs/concept_history.json.

Pool exhaustion fallback: if every concept has been displayed in the
window, reuse the **oldest** displayed concept (warning logged).
"""

from __future__ import annotations
from ..lib.jst import jst_today

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


def _upsert_entry(history: dict, entry: dict, *, date_key: str) -> None:
    """同じ日付の既存エントリを取り除いてから追記する（C185）.

    C185 (2026-08-29): 同日エントリは差し替える（再ラン耐性）。

    2026-08-28 に GitHub Actions の schedule が **+8 時間遅延**し、神山さんの
    手動実行（08:39 JST）の後に発火した（10:37 JST）。結果、archive commit が
    2 本作られ紙面が丸ごと差し替わった上、``.append()`` だったこの履歴に同じ
    日付が 2 件記録された。``page1_v3_history`` だけは ``save_essay`` が同日
    上書きだったため無傷で、その実装に揃えたのが本修正である。
    """
    entries = history.setdefault("history", [])
    stamp = entry.get(date_key)
    history["history"] = [e for e in entries if e.get(date_key) != stamp]
    history["history"].append(entry)


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


def _ever_shown_ids(history: dict) -> set[str]:
    """履歴に**一度でも**登場した concept_id の集合（C188）.

    ``_excluded_ids`` が「直近 N 日」で切るのに対し、こちらは全期間を見る。
    未出優先（段 2）の判定に使う。
    """
    out: set[str] = set()
    for entry in history.get("history", []):
        cid = entry.get("concept_id")
        if cid:
            out.add(cid)
    return out


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
        today = jst_today()
    if concepts is None:
        concepts = load_concepts()
    if history is None:
        history = load_history()
    if rng is None:
        rng = random.Random()

    # ------------------------------------------------------------------
    # C188 (2026-08-30): 3 段構えの選出
    #
    # 段 1  過去 exclusion_days 日に出たものを除外（従来どおり）
    # 段 2  **未出**（履歴に一度も登場していない）を優先
    # 段 3  未出が尽きたら既出から選ぶ（＝再訪）
    #
    # 従来は段 1 の後すぐ rng.choice していたため、実効候補 162 件のうち
    # 未出 107 件 / 既出 約 55 件が等確率で並び、**毎日およそ 34% で既出を
    # 引いていた**。結果、未出が 107 件（プールの 48%）残っているのに
    # 2026-07-16 以降で再掲が 8 件発生していた（環世界 5/17→8/16、
    # SECI モデル 5/20→7/31 など）。
    #
    # 段 3 で既出を永久に封印しないのは、同じ概念に別の文脈で再会すること
    # 自体に思考の蓄積としての意味があるため（神山さん判断）。段 3 は当面
    # ランダムでよい —— 段 1 の 60 日除外で最低限の間隔は担保されている。
    # 「久しぶりのものほど出やすい」重み付けは複雑になるので保留。
    #
    # なお旧実装の「枯渇時は最古を再利用」経路は**構造的に発動しえなかった**。
    # 60 日で表示できるのは最大 60 件で、222 件すべてが直近 60 日に出ることは
    # ありえないため。段 3 がその経路を実質的に置き換える。
    # ------------------------------------------------------------------
    excluded = _excluded_ids(history, today, exclusion_days)
    ever_shown = _ever_shown_ids(history)

    pool = [c for c in concepts if c["id"] not in excluded]
    unseen = [c for c in pool if c["id"] not in ever_shown]

    if unseen:
        stage = "unseen"
        candidates = unseen
    elif pool:
        stage = "revisit"
        candidates = pool
        print(
            f"[concept] 未出の概念が尽きました（プール {len(concepts)} 件、"
            f"直近 {exclusion_days} 日の除外 {len(excluded)} 件）。"
            f"既出 {len(pool)} 件からの再訪に切り替えます。"
            "—— concepts.yaml の補充を検討してください",
            file=sys.stderr,
        )
    else:
        # 段 1 で全部消えた（プールが exclusion_days より小さい場合のみ起きる。
        # 249 件 / 60 日では構造的に起きない）。従来どおり**最古**を再利用する
        # ——ランダムに戻すより間隔が最大化されるため。
        stage = "exhausted"
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
            candidates = list(concepts)

    selected = rng.choice(candidates)
    print(
        f"[concept] selected={selected['id']} stage={stage} "
        f"(pool={len(pool)} unseen={len(unseen)} excluded={len(excluded)})",
        file=sys.stderr,
    )

    if persist:
        # C185: 同日エントリは差し替え（再ラン耐性）。経緯は _upsert_entry を参照。
        _upsert_entry(history, {
            "concept_id": selected["id"],
            "name_ja": selected["name_ja"],
            "displayed_on": today.isoformat(),
            # C188: どの段で選ばれたか。既存エントリには無いので読む側は
            # .get("stage") で扱うこと。
            "stage": stage,
        }, date_key="displayed_on")
        save_history(history)

    return selected
