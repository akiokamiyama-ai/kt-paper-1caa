"""shadow 評価と本番 Sonnet の一致度を測る (C211, 2026-10-05).

C209 の比較指標:

1. 美意識 5 項目ごとの相関（本番 Sonnet 4.6 vs shadow）
2. ``final_score`` の順位相関
3. 紙面採用記事が shadow でも上位に来るか
4. 1 件あたりコストとレイテンシ

外部ライブラリを足さずに済ませる（Pearson と Spearman は数十行で書ける）。
numpy / scipy を入れると GHA runner の起動時間に乗るので避ける。
"""

from __future__ import annotations

import argparse
import collections
import json
import sys

from .base import AESTHETIC_KEYS
from . import store


def pearson(xs: list[float], ys: list[float]) -> float | None:
    n = len(xs)
    if n < 3:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx = sum((x - mx) ** 2 for x in xs) ** 0.5
    dy = sum((y - my) ** 2 for y in ys) ** 0.5
    if dx == 0 or dy == 0:
        return None          # 片方が定数。相関は定義されない
    return round(num / (dx * dy), 3)


def _ranks(vs: list[float]) -> list[float]:
    """同順位は平均順位にする（Spearman の正しい扱い）."""
    order = sorted(range(len(vs)), key=lambda i: vs[i])
    ranks = [0.0] * len(vs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and vs[order[j + 1]] == vs[order[i]]:
            j += 1
        avg = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def spearman(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 3:
        return None
    return pearson(_ranks(xs), _ranks(ys))


def _final(scores: dict) -> float | None:
    """本番と同じ式で final_score を出す（stage3 を再利用）."""
    from scripts.selector.stage3 import compute_final_score

    entry = {jp: scores.get(eng) for eng, jp in AESTHETIC_KEYS}
    if any(v is None for v in entry.values()):
        return None
    entry["美意識2_machine"] = None
    entry["美意識4_penalty"] = 0
    try:
        f, _ = compute_final_score(entry)
        return f
    except Exception:  # noqa: BLE001
        return None


def summarize(entries: list[dict]) -> dict:
    by_scorer = collections.defaultdict(list)
    for e in entries:
        if e.get("error") or not e.get("scores") or not e.get("baseline"):
            by_scorer[(e.get("scorer") or "?", "error")].append(e)
            continue
        by_scorer[(e.get("scorer") or "?", "ok")].append(e)

    out: dict = {}
    scorers = {k[0] for k in by_scorer}
    for s in sorted(scorers):
        ok = by_scorer[(s, "ok")]
        ng = by_scorer[(s, "error")]
        res: dict = {
            "n_ok": len(ok), "n_error": len(ng),
            "per_aesthetic": {}, "final_score": {},
            "cost_per_article": None, "latency_ms_median": None,
            "errors": collections.Counter(
                (e.get("error") or "no_scores")[:60] for e in ng
            ).most_common(5),
        }
        for eng, jp in AESTHETIC_KEYS:
            xs = [e["baseline"].get(jp) for e in ok]
            ys = [e["scores"].get(eng) for e in ok]
            pairs = [(x, y) for x, y in zip(xs, ys)
                     if isinstance(x, (int, float)) and isinstance(y, (int, float))]
            if len(pairs) < 3:
                res["per_aesthetic"][jp] = {"n": len(pairs)}
                continue
            a = [p[0] for p in pairs]; b = [p[1] for p in pairs]
            res["per_aesthetic"][jp] = {
                "n": len(pairs),
                "pearson": pearson(a, b),
                "spearman": spearman(a, b),
                "mean_baseline": round(sum(a) / len(a), 2),
                "mean_shadow": round(sum(b) / len(b), 2),
                "mean_confidence": (
                    round(sum(e.get("confidence", {}).get(eng, 0) for e in ok) / len(ok), 3)
                    if ok else None
                ),
            }
        fb, fs = [], []
        for e in ok:
            a = _final({eng: e["baseline"].get(jp) for eng, jp in AESTHETIC_KEYS})
            b = _final(e["scores"])
            if a is not None and b is not None:
                fb.append(a); fs.append(b)
        if len(fb) >= 3:
            res["final_score"] = {
                "n": len(fb), "pearson": pearson(fb, fs), "spearman": spearman(fb, fs),
            }
        if ok:
            res["cost_per_article"] = round(sum(e.get("cost_usd", 0) for e in ok) / len(ok), 8)
            lat = sorted(e.get("elapsed_ms", 0) for e in ok)
            res["latency_ms_median"] = lat[len(lat) // 2]
        out[s] = res
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="shadow 評価と本番の一致度を出す")
    ap.add_argument("--days", type=int, default=14)
    ap.add_argument("--json", action="store_true", help="JSON で出す")
    args = ap.parse_args()

    entries = store.load_range(args.days)
    if not entries:
        print(f"直近 {args.days} 日に shadow 評価ログがありません "
              f"(logs/shadow_eval_*.json)", file=sys.stderr)
        return 1
    res = summarize(entries)
    if args.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0
    for s, r in res.items():
        print(f"=== {s} — 成功 {r['n_ok']} 件 / 失敗 {r['n_error']} 件 ===")
        if r["errors"]:
            for msg, n in r["errors"]:
                print(f"    失敗 {n:>3}: {msg}")
        print(f"{'項目':<10}{'n':>5}{'Pearson':>9}{'Spearman':>10}"
              f"{'本番平均':>9}{'shadow':>9}{'confidence':>12}")
        for _eng, jp in AESTHETIC_KEYS:
            d = r["per_aesthetic"].get(jp, {})
            if d.get("n", 0) < 3:
                print(f"{jp:<10}{d.get('n',0):>5}   （件数不足）")
                continue
            print(f"{jp:<10}{d['n']:>5}{str(d['pearson']):>9}{str(d['spearman']):>10}"
                  f"{d['mean_baseline']:>9}{d['mean_shadow']:>9}"
                  f"{str(d['mean_confidence']):>12}")
        f = r["final_score"]
        if f:
            print(f"\n  final_score: n={f['n']} Pearson={f['pearson']} "
                  f"Spearman={f['spearman']}")
        print(f"  1 件あたり ${r['cost_per_article']} / レイテンシ中央 "
              f"{r['latency_ms_median']} ms\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
