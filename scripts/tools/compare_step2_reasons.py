"""「今朝の問い」が美意識 reasons にどれだけ依存しているかを実測する (C210, 2026-10-05).

背景
----
C209 で、stage2 の美意識 reasons が ``_summarize_aesthetic_reasons()`` 経由で
page2 Step 2（「今朝の問い」生成）のプロンプトに入っていることが判明した。
Jev は理由文を出さないため、page2 の評価を Jev に置き換えると問いの質が
落ちる懸念がある。

ただし C210 の調査で、**採用記事の 65% では美意識 reasons が実質 1 文**
（同じ文が 3 項目にコピーされ、美意識 5/6 は ``haiku_unscored``
プレースホルダ）であることが分かった。layer 1 の Haiku が 3 項目しか
採点せず、prefilter で Sonnet 評価に進まなかった記事がその結果を引き継ぐため。

そこで「reasons を外すと問いがどう変わるか」を実際に生成して比べる。

何を出すか
----------
採用済みの記事ごとに 3 本を並べる:

1. **本番** … その日の紙面に実際に載った問い（ログから。LLM を呼ばない）
2. **再現（reasons あり）** … 同じ入力で今もう一度生成したもの
3. **reasons なし** … 美意識の根拠だけを落として生成したもの

1 と 2 を並べるのは、**生成のばらつき**（同じ入力でも問いは変わる）と
**reasons を外した影響**を切り分けるため。2 と 3 の差が後者で、
1 と 2 の差が前者の目安になる。これが無いと「変わった」が
どちらの理由か分からない。

標本の選び方
------------
reasons が実質 1 文の群と 5 本ある群の **両方から** 取る（``--mix``、既定）。
5 本ある群で差が出ないなら、1 文の群で出るはずがない——つまり
最良ケースで測ることになる。

使い方
------
標本とコスト見積もりだけ見る（LLM を呼ばない、API キー不要）::

    python3 -m scripts.tools.compare_step2_reasons --dry-run

実行して Markdown を書き出す::

    ANTHROPIC_API_KEY=sk-ant-... python3 -m scripts.tools.compare_step2_reasons

紙面には一切影響しない（archive もログも書かず、``--out`` の .md だけ）。
"""

from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT = ROOT / "step2_reasons_comparison.md"
PLACEHOLDERS = ("haiku_unscored", "(no_reason_provided)", "missing_from_response")

# C210 実測: page2.step2 は 1 件あたり入力 ≈ 3,099 tok / 出力 ≈ 99 tok。
# Sonnet 4.6 ($3/$15) で約 $0.0108。1 記事につき 2 回生成する。
COST_PER_GENERATION_USD = 0.0108


def _load_candidates(scores_glob: str) -> list[dict]:
    """採用記事に美意識評価を突合して返す（新しい順）."""
    out = []
    for f in sorted(glob.glob(scores_glob), reverse=True):
        try:
            d = json.loads(Path(f).read_text(encoding="utf-8"))
        except Exception:
            continue
        day = d.get("date")
        sc_path = ROOT / "logs" / f"scores_{day}.json"
        if not sc_path.exists():
            continue
        try:
            sc = json.loads(sc_path.read_text(encoding="utf-8"))["evaluations"]
        except Exception:
            continue
        for url, e in d.get("evaluations", {}).items():
            s = sc.get(url)
            if not s or not e.get("company_key"):
                continue
            r = s.get("evaluation_reason") or {}
            uniq = {v for v in r.values() if v and v not in PLACEHOLDERS}
            out.append({
                "day": day, "url": url, "eval": e, "scores": s,
                "reasons": r, "n_unique": len(uniq),
            })
    return out


def _to_article(c: dict) -> dict:
    """step2 が期待する article dict を復元する."""
    e, s = c["eval"], c["scores"]
    return {
        "article_id": "art_cmp",
        "title": e.get("title"),
        "source_name": e.get("source_name"),
        "description": e.get("description") or e.get("title"),
        "body": "",
        "美意識1": s.get("美意識1"), "美意識3": s.get("美意識3"),
        "美意識5": s.get("美意識5"), "美意識6": s.get("美意識6"),
        "美意識8": s.get("美意識8"),
        "evaluation_reason": c["reasons"],
        "managerial_implication": e.get("managerial_implication"),
        "managerial_implication_reason": e.get("managerial_implication_reason"),
        "regulatory_signal": e.get("regulatory_signal"),
        "regulatory_signal_reason": e.get("regulatory_signal_reason"),
        "page2_final_score": e.get("page2_final_score"),
    }


def main() -> int:
    ap = argparse.ArgumentParser(
        description="「今朝の問い」の美意識 reasons 依存を実測する")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--n", type=int, default=6, help="標本数（既定 6）")
    ap.add_argument("--scores-glob", default=str(ROOT / "logs" / "page2_scores_*.json"),
                    help="page2_scores の glob。artifact を展開した先を指定してもよい")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    cands = _load_candidates(args.scores_glob)
    if not cands:
        print(f"採用記事が見つかりません: {args.scores_glob}", file=sys.stderr)
        print("page2_scores_*.json は .gitignore 対象です。GHA artifact を", file=sys.stderr)
        print("展開して --scores-glob でそのパスを指すか、logs/ に置いてください。", file=sys.stderr)
        return 1

    rich = [c for c in cands if c["n_unique"] >= 5]
    poor = [c for c in cands if c["n_unique"] <= 1]
    half = max(args.n // 2, 1)
    sample = rich[:half] + poor[: args.n - len(rich[:half])]

    print(f"採用記事 {len(cands)} 件（理由 5 本: {len(rich)} / 実質 1 文: {len(poor)}）")
    print(f"標本 {len(sample)} 件 — 両群から取る（最良ケースでも測るため）")
    print(f"見積もりコスト: 約 ${len(sample) * 2 * COST_PER_GENERATION_USD:.2f}"
          f"（1 記事 2 回 × {len(sample)} 件）\n")
    for c in sample:
        kind = "理由5本" if c["n_unique"] >= 5 else "実質1文"
        print(f"  {c['day']}  [{kind}] {c['eval']['company_key']:<13} "
              f"{(c['eval'].get('title') or '')[:42]}")

    if args.dry_run:
        print("\n--dry-run のため LLM は呼びませんでした。")
        return 0

    from scripts.selector import page2

    md = ["# 「今朝の問い」— 美意識 reasons あり / なし の比較", "",
          "C210 (2026-10-05)。各記事について 3 本を並べる。", "",
          "- **本番** … その日の紙面に実際に載った問い（ログ）",
          "- **再現（reasons あり）** … 同じ入力で今もう一度生成",
          "- **reasons なし** … 美意識の根拠だけ落として生成", "",
          "**本番と再現の差が生成のばらつき**、**再現と「なし」の差が reasons の効果**。", ""]
    total_cost = 0.0
    for i, c in enumerate(sample, 1):
        e = c["eval"]
        kind = "理由5本" if c["n_unique"] >= 5 else "実質1文（3項目に同一文＋2項目プレースホルダ）"
        art_with = _to_article(c)
        art_without = dict(art_with); art_without["evaluation_reason"] = {}
        print(f"\n[{i}/{len(sample)}] {(e.get('title') or '')[:40]} …", flush=True)
        try:
            q_with, _, c1 = page2.generate_morning_question(art_with, e["company_key"])
            q_without, _, c2 = page2.generate_morning_question(art_without, e["company_key"])
        except Exception as ex:  # noqa: BLE001
            print(f"  失敗: {type(ex).__name__}: {ex}", file=sys.stderr)
            continue
        total_cost += (c1 or 0) + (c2 or 0)
        md += [
            f"## {i}. {e.get('title')}", "",
            f"- {c['day']} / {e['company_key']} / {e.get('source_name')}",
            f"- 美意識: 1={art_with['美意識1']} 3={art_with['美意識3']} "
            f"5={art_with['美意識5']} 6={art_with['美意識6']} 8={art_with['美意識8']}",
            f"- reasons の状態: **{kind}**",
            f"- 経営的含意: {art_with['managerial_implication']} — "
            f"{art_with['managerial_implication_reason']}", "",
            "| | 問い |", "|---|---|",
            f"| 本番 | {e.get('morning_question') or '(なし)'} |",
            f"| 再現（reasons あり） | {q_with} |",
            f"| **reasons なし** | {q_without} |", "",
        ]
        print(f"  あり: {q_with}")
        print(f"  なし: {q_without}")

    md += ["---", "", f"実コスト: ${total_cost:.4f}", ""]
    args.out.write_text("\n".join(md), encoding="utf-8")
    print(f"\n完了: {args.out}  実コスト ${total_cost:.4f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
