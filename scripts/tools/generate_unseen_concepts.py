"""未掲載の概念について、4 面コラム本文をまとめて生成する (C206, 2026-09-22).

なぜこれがあるか
----------------
Obsidian の保管庫に概念ノートとして取り込むため、既出分は archive から本文を
回収できたが、**未掲載の概念は本文がまだ存在しない**。紙面の日次ランを待たず
に先に書き起こすための一括生成ツール。

本番（``regen_front_page_v2.build_page_four``）とまったく同じ呼び方をする::

    related = related_concepts.select_related(concept, concepts)
    result  = concept_writer.write_essay(concept, related)

つまり生成される本文は、その概念が実際に紙面に出たときと同じ品質・同じ体裁。
1 概念につき LLM 呼び出しは **1 回**（``page4.concept``、本文と関連概念の解説を
まとめて生成）。

紙面には一切影響しない
----------------------
- ``archive/`` を書かない
- ``logs/concept_history.json`` を更新しない（＝この生成で「既出」にならない。
  対象概念は今後も通常どおり紙面に選出される）
- 書き込むのは ``--out`` の CSV と、``logs/llm_usage_<日付>.json``（既定で
  .gitignore 対象）だけ

使い方
------
まず件数とコスト見積もりだけ見る（**LLM を呼ばない**、API キー不要）::

    python3 -m scripts.tools.generate_unseen_concepts --dry-run

実際に生成する（API キーはこのコマンド限りの一時設定）::

    ANTHROPIC_API_KEY=sk-ant-... python3 -m scripts.tools.generate_unseen_concepts

途中で止まっても、既に書けた分は ``--out`` に残る。同じコマンドを再実行すると
**出力済みの概念は自動で飛ばす**ので、続きから再開できる。
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MARKED = ROOT / "concepts_export_2026-09-22.csv"
DEFAULT_OUT = ROOT / "concepts_unseen_bodies.csv"
MARK_COLUMN = "Obsidian"

# C204 の実測（直近 7 日の page4.concept、7 呼び出し）。
#   入力 1,259 tok / 出力 916 tok / 1 件あたり $0.0175（Sonnet 4.6 $3/$15）
COST_PER_CONCEPT_USD = 0.0175

FIELDS = [
    "id", "name_ja", "name_en", "domain", "difficulty",
    "thinkers", "related", "essay", "essay_chars",
    "related_notes", "is_fallback", "cost_usd", "generated_at",
]


def _load_targets(marked_csv: Path, mark: str) -> list[dict]:
    """印の付いた未掲載概念を、concepts.yaml の完全な dict で返す."""
    concepts = yaml.safe_load((ROOT / "data" / "concepts.yaml").read_text(encoding="utf-8"))
    by_id = {c["id"]: c for c in concepts}

    hist = json.loads((ROOT / "logs" / "concept_history.json").read_text(encoding="utf-8"))
    seen_ids = {r["concept_id"] for r in hist["history"]}

    with marked_csv.open(encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    if rows and MARK_COLUMN not in rows[0]:
        raise SystemExit(
            f"{marked_csv.name} に '{MARK_COLUMN}' 列がありません。"
            f"見つかった列: {list(rows[0])}"
        )

    targets = []
    for r in rows:
        if (r.get(MARK_COLUMN) or "").strip() != mark:
            continue
        cid = r["id"]
        # 「未掲載」の判定は CSV の status ではなく **履歴を正** とする
        # （CSV は表計算で編集されており、値が書き換わりうるため）。
        if cid in seen_ids:
            continue
        if cid not in by_id:
            print(f"  ! {cid} は concepts.yaml に無い。skip", file=sys.stderr)
            continue
        targets.append(by_id[cid])
    return targets, concepts


def _already_done(out_path: Path) -> set[str]:
    if not out_path.exists():
        return set()
    with out_path.open(encoding="utf-8-sig") as f:
        return {r["id"] for r in csv.DictReader(f) if r.get("id")}


def main() -> int:
    ap = argparse.ArgumentParser(
        description="印の付いた未掲載概念の 4 面コラム本文を一括生成する"
    )
    ap.add_argument("--marked", type=Path, default=DEFAULT_MARKED,
                    help=f"印を付けた CSV（既定: {DEFAULT_MARKED.name}）")
    ap.add_argument("--mark", default="〇", help="対象を示す印（既定: 〇）")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT,
                    help=f"出力 CSV（既定: {DEFAULT_OUT.name}）")
    ap.add_argument("--dry-run", action="store_true",
                    help="対象と見積もりだけ表示し、LLM を呼ばない")
    ap.add_argument("--limit", type=int, default=0,
                    help="先頭 N 件だけ処理（試し打ち用。0 で全件）")
    ap.add_argument("--sleep", type=float, default=1.0,
                    help="呼び出し間隔の秒数（既定 1.0）")
    args = ap.parse_args()

    targets, concepts = _load_targets(args.marked, args.mark)
    done = _already_done(args.out)
    todo = [c for c in targets if c["id"] not in done]
    if args.limit:
        todo = todo[: args.limit]

    print(f"印 '{args.mark}' の未掲載概念: {len(targets)} 件")
    if done:
        print(f"  うち出力済み（skip）: {len(done & {c['id'] for c in targets})} 件")
    print(f"  今回の対象          : {len(todo)} 件")
    print(f"  見積もりコスト      : 約 ${len(todo) * COST_PER_CONCEPT_USD:.2f} "
          f"（1 件 ${COST_PER_CONCEPT_USD} × {len(todo)}）")
    print()
    for i, c in enumerate(todo, 1):
        print(f"  {i:>2}. {c['name_ja']}  ({c['domain']})")

    if args.dry_run:
        print("\n--dry-run のため LLM は呼びませんでした。")
        return 0
    if not todo:
        print("\n対象がありません。")
        return 0

    # 実行時にだけ import する（--dry-run は API キー無しで通したい）。
    from scripts.page4 import concept_writer, related_concepts

    print()
    new_file = not args.out.exists()
    total_cost = 0.0
    with args.out.open("a", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if new_file:
            w.writeheader()
        for i, concept in enumerate(todo, 1):
            print(f"[{i}/{len(todo)}] {concept['name_ja']} …", end=" ", flush=True)
            try:
                related = related_concepts.select_related(concept, concepts)
                res = concept_writer.write_essay(concept, related)
            except Exception as e:  # noqa: BLE001 — 1 件の失敗で全体を止めない
                print(f"失敗: {type(e).__name__}: {e}", file=sys.stderr)
                continue
            essay = res["essay"]
            total_cost += res.get("cost_usd", 0.0) or 0.0
            w.writerow({
                "id": concept["id"],
                "name_ja": concept["name_ja"],
                "name_en": concept["name_en"],
                "domain": concept["domain"],
                "difficulty": concept.get("difficulty", ""),
                "thinkers": "; ".join(concept.get("thinkers") or []),
                "related": "; ".join(r["id"] for r in (res.get("related") or [])),
                "essay": essay,
                "essay_chars": len(essay),
                "related_notes": " || ".join(
                    f"{r['name_ja']}: {r.get('note', '')}"
                    for r in (res.get("related") or [])
                ),
                "is_fallback": res.get("is_fallback", False),
                "cost_usd": round(res.get("cost_usd", 0.0) or 0.0, 6),
                "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            })
            f.flush()  # 途中で止まっても既出分を失わない
            flag = "  ※fallback" if res.get("is_fallback") else ""
            print(f"{len(essay)} 字  ${res.get('cost_usd', 0.0):.4f}{flag}")
            if args.sleep and i < len(todo):
                time.sleep(args.sleep)

    print(f"\n完了: {args.out}")
    print(f"  実コスト: ${total_cost:.4f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
