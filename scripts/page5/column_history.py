"""第5面「AIかみやまの一筆」の生成結果を日次で記録する (C201, 2026-09-21).

なぜこのファイルがあるか
------------------------
第5面の一筆は **Tribune で唯一 Anthropic API を経由しない生成経路**
（miibo API）である。miibo が落ちると ``write_column`` は固定文の
fallback に倒れて紙面自体は成立するため、**失敗しても静かに成功に見える**。

C200 (2026-09-21) の運用チェックで、この失敗が履歴から検知できない状態が
判明した。発端は ``logs/page5_history.json`` の ``ai_kamiyama_called`` が
17 日すべて ``False`` だったこと。当初は「``update_history_column_fields``
が本番から呼ばれていない配線漏れ」と見立てたが、調査すると真因は別だった。

    C155 (2026-08-10) で第5面を作り直したとき、セレンディピティ枠は
    第3面 6 枠目へ移設され、一筆は専用の ``ai_kamiyama_selector`` が
    選んだ**別の記事**を論評するようになった。

    ``logs/page5_history.json`` は（ファイル名は旧名のまま）
    **第3面セレンディピティ枠の履歴**であり続けている
    （``scripts/selector/serendipity.py`` の docstring 参照）。

    つまり ``ai_kamiyama_called`` 等 3 フィールドは C155 以前の
    2 枠構成の名残で、**いま記録されている記事と一筆は無関係**である。
    ``update_history_column_fields`` をどこから呼んでも、
    「別の記事のエントリ」に一筆の成否を書き込むことにしかならない。

そこで旧フィールドを配線するのではなく、第5面専用の履歴をここに新設する。
実際に論評された記事と、その生成の成否が 1 対 1 で対応する。

記録する内容
------------
``logs/page5_column_history.json``::

    {"history": [
      {"displayed_on": "2026-09-21",
       "article_url": "https://...",        # 一筆が論評した記事（休載時 None）
       "article_title": "...",
       "miibo_called": true,                # write_column を呼んだか
       "miibo_failed": false,               # API 失敗 or 空応答
       "fallback_used": false,              # 固定文に倒れたか
       "elapsed_ms": 4211,
       "column_title": "...",
       "column_body_chars": 512,
       "is_placeholder": false}             # 候補ゼロで面ごと休載
    ]}

``miibo_failed`` / ``fallback_used`` を日次で見れば、静かな劣化に気づける。

冪等性
------
同一 ``displayed_on`` の再実行は **置換**（upsert）する。C185 の二重実行
ガードと同じ思想で、二重 append を作らない。
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

LOG_DIR = Path(__file__).resolve().parent.parent.parent / "logs"
HISTORY_PATH = LOG_DIR / "page5_column_history.json"


def load_history(*, path: Path | None = None) -> dict:
    p = path or HISTORY_PATH
    if not p.exists():
        return {"history": []}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        # 観測ログの破損で紙面を落とさない。
        print(
            f"[page5/column_history] load failed ({type(e).__name__}), "
            "treating as empty",
            file=sys.stderr,
        )
        return {"history": []}
    if not isinstance(data, dict) or not isinstance(data.get("history"), list):
        return {"history": []}
    return data


def save_history(data: dict, *, path: Path | None = None) -> None:
    p = path or HISTORY_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def record_column_result(
    *,
    target_date: date,
    article: dict | None,
    column: dict | None,
    path: Path | None = None,
) -> dict:
    """一筆の生成結果を 1 日分記録して、書いたエントリを返す.

    ``article`` / ``column`` が None なら休載（候補ゼロ）として記録する。

    観測のための記録なので、**ここでの例外は紙面を落としてはならない**。
    書き込みに失敗しても呼び出し側には返り値だけ返し、stderr に出す。
    """
    col = column or {}
    is_placeholder = article is None or column is None

    entry = {
        "displayed_on": target_date.isoformat(),
        "article_url": (article or {}).get("url"),
        "article_title": (article or {}).get("title"),
        # write_column は全リターン経路で ai_kamiyama_called=True を返す。
        # 呼ばなかった（＝休載）ときだけ False になる。
        "miibo_called": bool(col.get("ai_kamiyama_called", False)),
        "miibo_failed": bool(col.get("ai_kamiyama_failed", False)),
        "fallback_used": bool(col.get("fallback_used", False)),
        "elapsed_ms": int(col.get("elapsed_ms", 0) or 0),
        "column_title": col.get("column_title"),
        "column_body_chars": len((col.get("column_body") or "")),
        "is_placeholder": is_placeholder,
    }

    try:
        h = load_history(path=path)
        rows = [r for r in h["history"] if r.get("displayed_on") != entry["displayed_on"]]
        rows.append(entry)
        rows.sort(key=lambda r: r.get("displayed_on") or "")
        h["history"] = rows
        save_history(h, path=path)
    except Exception as e:  # noqa: BLE001 — 観測で紙面を落とさない
        print(
            f"[page5/column_history] record failed (non-fatal): {type(e).__name__}: {e}",
            file=sys.stderr,
        )
        return entry

    if entry["is_placeholder"]:
        print("[page5/column_history] 休載を記録しました", file=sys.stderr)
    elif entry["miibo_failed"] or entry["fallback_used"]:
        # 静かな劣化を目立たせる。ここが C200 で見えなかったもの。
        print(
            f"[page5/column_history] WARN: miibo 生成が fallback に倒れました "
            f"(failed={entry['miibo_failed']}, fallback={entry['fallback_used']})",
            file=sys.stderr,
        )
    return entry


def recent_failures(days: int = 14, *, path: Path | None = None) -> list[dict]:
    """直近 ``days`` 件のうち fallback / 失敗だったエントリを返す（点検用）."""
    rows = load_history(path=path)["history"][-days:]
    return [r for r in rows if r.get("miibo_failed") or r.get("fallback_used")]
