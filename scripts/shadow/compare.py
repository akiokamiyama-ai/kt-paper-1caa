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
from pathlib import Path

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


def cross_compare(entries: list[dict], a: str = "jev",
                  b: str = "jev_fulltext") -> dict:
    """C214: scorer 同士の相関（本番を介さない A vs B）.

    同じ ``(url, caller)`` で両方の scorer が成功している組だけを使う。
    ``haiku_unscored`` の項目は除外する（baseline と同じ扱い）。
    """
    by_key: dict[tuple, dict[str, dict]] = collections.defaultdict(dict)
    for e in entries:
        if e.get("error") or not e.get("scores"):
            continue
        by_key[(e.get("url"), e.get("caller"))][e.get("scorer")] = e

    both = [(v[a], v[b]) for v in by_key.values() if a in v and b in v]
    out: dict = {"n_pairs": len(both), "per_aesthetic": {}, "final_score": {}}
    if not both:
        return out
    for eng, jp in AESTHETIC_KEYS:
        xs, ys = [], []
        for ea, eb in both:
            if not _usable(ea, jp):      # baseline の未採点印は共通
                continue
            x, y = ea["scores"].get(eng), eb["scores"].get(eng)
            if isinstance(x, (int, float)) and isinstance(y, (int, float)):
                xs.append(x); ys.append(y)
        d = {"n": len(xs)}
        if len(xs) >= 3:
            d.update({"spearman": spearman(xs, ys), "pearson": pearson(xs, ys),
                      "mean_a": round(sum(xs) / len(xs), 2),
                      "mean_b": round(sum(ys) / len(ys), 2)})
        out["per_aesthetic"][jp] = d
    fa, fb = [], []
    for ea, eb in both:
        if (ea.get("baseline_meta") or {}).get("unscored"):
            continue
        x, y = _final(ea["scores"]), _final(eb["scores"])
        if x is not None and y is not None:
            fa.append(x); fb.append(y)
    if len(fa) >= 3:
        out["final_score"] = {"n": len(fa), "spearman": spearman(fa, fb),
                              "pearson": pearson(fa, fb)}
    # 入力規模の差（B が実際に多く読めているか）
    sa = [e.get("state_chars") for e, _ in both if e.get("state_chars")]
    sb = [e.get("state_chars") for _, e in both if e.get("state_chars")]
    if sa and sb:
        out["state_chars"] = {
            "a_median": sorted(sa)[len(sa) // 2],
            "b_median": sorted(sb)[len(sb) // 2],
            "b_larger": sum(1 for x, y in zip(sa, sb) if y > x),
            "n": len(sa),
        }
    return out


def divergent(entries: list[dict], *, scorer: str = "jev_fulltext",
              top: int = 5) -> list[dict]:
    """C214: 本番と ``scorer`` が最も割れた記事を返す（人が読んで判定する用）.

    判定材料なので **final_score の差**で並べる。全 5 項目が採点済みの記事
    だけを対象にする（未採点があると差が項目欠落に由来してしまう）。
    """
    rows = []
    for e in entries:
        if e.get("scorer") != scorer or e.get("error") or not e.get("scores"):
            continue
        if (e.get("baseline_meta") or {}).get("unscored"):
            continue
        base = _final({eng: e["baseline"].get(jp) for eng, jp in AESTHETIC_KEYS})
        shad = _final(e["scores"])
        if base is None or shad is None:
            continue
        rows.append({
            "date": e.get("date"), "caller": e.get("caller"),
            "title": e.get("title"), "url": e.get("url"),
            "baseline_final": round(base, 1), "shadow_final": round(shad, 1),
            "diff": round(shad - base, 1),
            "baseline": e.get("baseline"),
            "shadow": {jp: e["scores"].get(eng) for eng, jp in AESTHETIC_KEYS},
            "confidence": e.get("confidence"),
            "state_chars": e.get("state_chars"),
        })
    rows.sort(key=lambda r: -abs(r["diff"]))
    return rows[:top]


def main() -> int:
    ap = argparse.ArgumentParser(description="shadow 評価と本番の一致度を出す")
    ap.add_argument("--days", type=int, default=14)
    ap.add_argument("--json", action="store_true", help="JSON で出す")
    ap.add_argument("--divergent", type=int, default=0, metavar="N",
                    help="本番と最も割れた記事 N 件を出す（人が読んで判定する用）")
    ap.add_argument("--divergent-scorer", default="jev_fulltext")
    ap.add_argument("--log-dir", type=Path, default=None,
                    help="shadow ログの場所。GHA artifact を展開した先を指定する"
                         "（既定は logs/。shadow ログは .gitignore 対象で"
                         "artifact にしか残らない）")
    args = ap.parse_args()

    entries = store.load_range(args.days, log_dir=args.log_dir)
    if not entries:
        where = args.log_dir or "logs/"
        print(f"直近 {args.days} 日に shadow 評価ログがありません（{where}）",
              file=sys.stderr)
        print("shadow ログは .gitignore 対象で GHA artifact にしか残りません。",
              file=sys.stderr)
        print("次のように展開してから --log-dir を指すか、logs/ に置いてください:",
              file=sys.stderr)
        print("  bash scripts/tools/fetch_shadow_logs.sh 14 /tmp/shadow",
              file=sys.stderr)
        print("  python3 -m scripts.shadow.compare --days 14 --log-dir /tmp/shadow",
              file=sys.stderr)
        return 1
    if args.divergent:
        rows = divergent(entries, scorer=args.divergent_scorer, top=args.divergent)
        print(f"# 本番 vs {args.divergent_scorer} が最も割れた {len(rows)} 件\n")
        print("final_score の差の大きい順。神山さんが読んで、どちらの評価が")
        print("妥当かを判定してください。\n")
        for i, r in enumerate(rows, 1):
            print(f"## {i}. {r['title']}")
            print(f"- {r['date']} / {r['caller']} / {r['url']}")
            print(f"- final_score: 本番 {r['baseline_final']} → "
                  f"shadow {r['shadow_final']}  （差 {r['diff']:+}）")
            print(f"- 入力の規模: {r['state_chars']} 字")
            print(f"  {'項目':<10}{'本番':>6}{'shadow':>8}{'conf':>7}")
            for _eng, jp in AESTHETIC_KEYS:
                print(f"  {jp:<10}{r['baseline'].get(jp):>6}"
                      f"{r['shadow'].get(jp):>8}"
                      f"{str((r.get('confidence') or {}).get(_eng, '-')):>7}")
            print()
        return 0

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

    # C214: scorer 同士（本番を介さない）
    x = cross_compare(entries)
    if x["n_pairs"]:
        print(f"=== jev vs jev_fulltext（同一記事で両方成功 {x['n_pairs']} 組）===")
        print(f"{'項目':<10}{'n':>5}{'Spearman':>10}{'Pearson':>9}{'A平均':>8}{'B平均':>8}")
        for _eng, jp in AESTHETIC_KEYS:
            d = x["per_aesthetic"].get(jp, {})
            if d.get("n", 0) < 3:
                print(f"{jp:<10}{d.get('n',0):>5}   （件数不足）"); continue
            print(f"{jp:<10}{d['n']:>5}{str(d['spearman']):>10}"
                  f"{str(d['pearson']):>9}{d['mean_a']:>8}{d['mean_b']:>8}")
        f = x["final_score"]
        if f:
            print(f"\n  final_score: n={f['n']} Spearman={f['spearman']}")
        sc = x.get("state_chars")
        if sc:
            print(f"  入力規模の中央値: A {sc['a_median']} 字 / B {sc['b_median']} 字"
                  f"  （B のほうが大きい組 {sc['b_larger']}/{sc['n']}）")
            if sc["b_larger"] == 0:
                print("  ★ B が A より大きい組が 0。本文が取れていないので"
                      "A と B は同じ入力になっている。")
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
