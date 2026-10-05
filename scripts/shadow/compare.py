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


def _layer_group(e: dict) -> str:
    """baseline を層でまとめる。``haiku`` 群は美意識5/6 が未採点."""
    m = e.get("baseline_meta") or {}
    mode = m.get("evaluation_mode") or ""
    if mode.startswith("haiku"):
        return "haiku"
    if mode.startswith("sonnet"):
        return "sonnet_full"
    return "unknown"


def _usable(e: dict, jp: str) -> bool:
    """この項目を相関計算に使えるか.

    C213: ``haiku_unscored`` の項目は **Sonnet が 0 と判断したのではなく
    採点していない**。除外する。理由文が残っている 0 は正当な 0 なので使う。
    """
    return jp not in ((e.get("baseline_meta") or {}).get("unscored") or [])


def summarize(entries: list[dict], *, by_layer: bool = True) -> dict:
    """shadow と本番の一致度をまとめる.

    **Spearman（順位相関）を主指標にする。** Jev は代表値の都合で
    1.0 未満を返せず（0–2 帯 = 1.0）、本番 Sonnet は 0 を返す。値域が
    [1.0, 9.5] 対 [0, 10] で揃わないので、Pearson は系統的に圧縮される。
    置き換えの可否を決めるのは「同じ記事を同じ順に並べられるか」なので
    順位相関で見る。Pearson も参考として併記する。
    """
    groups: dict[tuple, list[dict]] = collections.defaultdict(list)
    for e in entries:
        s = e.get("scorer") or "?"
        g = _layer_group(e) if by_layer else "all"
        key = (s, g)
        groups[key].append(e)

    out: dict = {}
    for (scorer, layer), rows in sorted(groups.items()):
        ok = [e for e in rows
              if not e.get("error") and e.get("scores") and e.get("baseline")]
        ng = [e for e in rows if e not in ok]
        res: dict = {
            "n_ok": len(ok), "n_error": len(ng),
            "per_aesthetic": {}, "final_score": {},
            "cost_per_article": None, "latency_ms_median": None,
            "errors": collections.Counter(
                (e.get("error") or "no_scores")[:60] for e in ng
            ).most_common(5),
        }
        for eng, jp in AESTHETIC_KEYS:
            pairs = []
            n_excluded = 0
            for e in ok:
                if not _usable(e, jp):
                    n_excluded += 1
                    continue
                x = e["baseline"].get(jp)
                y = e["scores"].get(eng)
                if isinstance(x, (int, float)) and isinstance(y, (int, float)):
                    pairs.append((x, y))
            d: dict = {"n": len(pairs), "excluded_unscored": n_excluded}
            if len(pairs) >= 3:
                a = [p[0] for p in pairs]; b = [p[1] for p in pairs]
                d.update({
                    "spearman": spearman(a, b),       # ★主指標
                    "pearson": pearson(a, b),         # 参考
                    "mean_baseline": round(sum(a) / len(a), 2),
                    "mean_shadow": round(sum(b) / len(b), 2),
                    "mean_confidence": (
                        round(sum(e.get("confidence", {}).get(eng, 0)
                                  for e in ok) / len(ok), 3) if ok else None
                    ),
                })
            res["per_aesthetic"][jp] = d

        # final_score は **全 5 項目が採点済みの記事だけ**で出す。
        fb, fs = [], []
        for e in ok:
            if (e.get("baseline_meta") or {}).get("unscored"):
                continue
            a = _final({eng: e["baseline"].get(jp) for eng, jp in AESTHETIC_KEYS})
            b = _final(e["scores"])
            if a is not None and b is not None:
                fb.append(a); fs.append(b)
        if len(fb) >= 3:
            res["final_score"] = {
                "n": len(fb), "spearman": spearman(fb, fs), "pearson": pearson(fb, fs),
            }
        else:
            res["final_score"] = {"n": len(fb)}
        if ok:
            res["cost_per_article"] = round(
                sum(e.get("cost_usd", 0) for e in ok) / len(ok), 8)
            lat = sorted(e.get("elapsed_ms", 0) for e in ok)
            res["latency_ms_median"] = lat[len(lat) // 2]
        out[f"{scorer} / {layer}"] = res
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
    print(f"対象 {len(entries)} 件 / 直近 {args.days} 日\n")
    print("※ Jev は代表値の都合で 1.0 未満を返せない（0–2 帯 = 1.0）。")
    print("  本番は 0 を返すため値域が [1.0, 9.5] 対 [0, 10] で揃わない。")
    print("  判定は **Spearman（順位相関）** で行う。Pearson は参考。")
    print("※ haiku_unscored（Haiku が採点していない美意識5/6）は除外している。\n")
    for s_, r in res.items():
        print(f"=== {s_} — 成功 {r['n_ok']} 件 / 失敗 {r['n_error']} 件 ===")
        for msg, n in r["errors"]:
            print(f"    失敗 {n:>3}: {msg}")
        print(f"{'項目':<10}{'n':>5}{'除外':>5}{'Spearman':>10}{'Pearson':>9}"
              f"{'本番平均':>9}{'shadow':>9}{'conf':>7}")
        for _eng, jp in AESTHETIC_KEYS:
            d = r["per_aesthetic"].get(jp, {})
            if d.get("n", 0) < 3:
                print(f"{jp:<10}{d.get('n',0):>5}{d.get('excluded_unscored',0):>5}"
                      f"   （件数不足）")
                continue
            print(f"{jp:<10}{d['n']:>5}{d['excluded_unscored']:>5}"
                  f"{str(d['spearman']):>10}{str(d['pearson']):>9}"
                  f"{d['mean_baseline']:>9}{d['mean_shadow']:>9}"
                  f"{str(d['mean_confidence']):>7}")
        f = r["final_score"]
        if f.get("spearman") is not None:
            print(f"\n  final_score（全項目採点済みのみ）: n={f['n']} "
                  f"Spearman={f['spearman']} Pearson={f['pearson']}")
        else:
            print(f"\n  final_score: n={f.get('n', 0)}（件数不足）")
        print(f"  1 件あたり ${r['cost_per_article']} / レイテンシ中央 "
              f"{r['latency_ms_median']} ms\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
