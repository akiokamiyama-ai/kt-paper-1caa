"""概念ノートを Obsidian 用の Markdown として書き出す (C206, 2026-09-22).

本文の出どころは 2 つ:

* **掲載済み** … ``archive/<初出日>.html`` の第 4 面コラムから回収する（LLM 不要）
* **未掲載**   … ``scripts/tools/generate_unseen_concepts.py`` が先に生成した
  ``concepts_unseen_bodies.csv`` から読む

第 4 面の切り出しについて（ここを間違えると静かに壊れる）
--------------------------------------------------------
最初の実装は「``今日の概念`` を見つけて、そこから 14,000 文字を見て、その中で
**最も長い行**を本文とみなす」というものだった。これは 2 通りに壊れた。

1. **窓が Page V まで届いていた。** 第 5 面の AIかみやまコラムのほうが長いため、
   「暗黙知」のノートに映画『タクシー』論が入るなどの取り違えが起きた。
2. **本文が複数段落のとき、1 段落しか取れなかった。** 対象 39 件のうち
   **30 件**が複数段落で、たとえば「知識経営」は 7 段落 2,132 字あるのに
   最長の 1 段落だけが残っていた。

そこで「長さ」ではなく**構造**で切る:

    — Page IV —
      Arts & Letters · …          ← バナー
      今日の概念 / 今週の概念        ← 見出し（初期は「今週」だった）
      <和名> / <英名> / <領域>
      代表：…                      ← ここまでヘッダ
      <本文の段落 1..n>            ← ★ここが本文
      この概念とつながるもの         ← ここで本文おわり
      <関連名> / <英名> / <解説>
    — Page V —                    ← 区間の終わり

使い方::

    python3 -m scripts.tools.export_obsidian_concepts            # 〇 の付いた 62 件
    python3 -m scripts.tools.export_obsidian_concepts --all      # 既出全件
    python3 -m scripts.tools.export_obsidian_concepts --out DIR
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
MARKED_CSV = ROOT / "concepts_export_2026-09-22.csv"
UNSEEN_CSV = ROOT / "concepts_unseen_bodies.csv"
MARK_COLUMN = "Obsidian"
DEFAULT_OUT = ROOT / "obsidian_concepts"

# Windows / macOS / Obsidian で使えないファイル名文字
_BAD_FILENAME = re.compile(r'[\\/:*?"<>|]')
# Obsidian のタグに使えない文字（日本語は使える）
_BAD_TAG = re.compile(r"[\s#/\\:*?\"<>|（）()・、。]+")


def _slug_tag(text: str) -> str:
    return _BAD_TAG.sub("_", text).strip("_")


def _safe_filename(name: str) -> str:
    return _BAD_FILENAME.sub("_", name).strip()


def _strip_tags(frag: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", frag)).strip()


def parse_page4(day: str, name_ja: str) -> dict | None:
    """archive の第 4 面から本文段落と関連概念を **CSS クラスで** 切り出す.

    行の長さで推測しない。第 4 面には概念コラムのほかに学術ニュース
    (``academic-column``) が同居しており、長さベースの判定では英文記事まで
    拾ってしまう（実際に拾った）。紙面はクラス名を持っているのでそれを使う::

        div.concept-essay  > p …        本文の段落
        div.related-concept-item        関連概念
          span.rc-name / .rc-note
    """
    p = ROOT / "archive" / f"{day}.html"
    if not p.exists():
        return None
    doc = p.read_text(encoding="utf-8").split("</style>")[-1]

    # 概念コラムのブロックだけを取り出す（学術ニュースを含めない）。
    m = re.search(r'<div class="concept-essay">(.*?)</div>', doc, re.S)
    if not m:
        return None
    paras = [_strip_tags(x) for x in re.findall(r"<p[^>]*>(.*?)</p>", m.group(1), re.S)]
    paras = [x for x in paras if x]
    if not paras:
        return None

    # 概念名が一致することを確認（別の日の紙面を読んでいないか）。
    t = re.search(r'class="concept-title"[^>]*>(.*?)<', doc, re.S)
    if t and _strip_tags(t.group(1)) != name_ja:
        return None

    rel: list[tuple[str, str]] = []
    for item in re.findall(r'<li class="related-concept-item".*?</li>', doc, re.S):
        nm = re.search(r'class="rc-name"[^>]*>(.*?)<', item, re.S)
        nt = re.search(r'class="rc-note"[^>]*>(.*?)</', item, re.S)
        if nm and nt:
            rel.append((_strip_tags(nm.group(1)), _strip_tags(nt.group(1))))
    return {"paras": paras, "rel": rel}


def build_note(concept: dict, *, body_paras: list[str], rel: list[tuple[str, str]],
               rel_ids: list[str], day: str | None, published: bool,
               name_of: dict[str, str]) -> str:
    nj, ne = concept["name_ja"], concept["name_en"]
    domain = concept["domain"]
    top = domain.split("・")[0]

    fm = [
        "---",
        f'title: "{nj}"',
        f'aliases: ["{ne}", "{concept["id"]}"]',
        f'domain: "{domain}"',
        f'domain_top: "{top}"',
        f"difficulty: {concept.get('difficulty', '')}",
        "tags:",
        "  - concept",
        f"  - {_slug_tag(top)}",
        f"  - {'掲載済み' if published else '未掲載'}",
    ]
    if concept.get("thinkers"):
        fm.append("thinkers:")
        fm += [f'  - "{t}"' for t in concept["thinkers"]]
    fm += [
        f"published_on: {day or ''}",
        f"source: {'Kamiyama Tribune 第4面' if published else 'concept_writer（未掲載分を先行生成）'}",
        "exported: 2026-09-22",
        "---",
        "",
        f"# {nj}",
        "",
        f"*{ne}* — {domain}",
        "",
    ]
    out = fm
    if concept.get("thinkers"):
        out += [f"> 代表: {'、'.join(concept['thinkers'])}", ""]
    out += ["## 本文", ""]
    for para in body_paras:
        out += [para, ""]
    if rel:
        out += ["## この概念とつながるもの", ""]
        for nm, note in rel:
            out += [f"### [[{nm}]]", "", note, ""]
    if rel_ids:
        out += ["## 関連概念", "",
                " · ".join(f"[[{name_of.get(i, i)}]]" for i in rel_ids), ""]
    seed = re.sub(r"\s*\n\s*", " ", concept["seed"].strip())
    out += ["## 種（concepts.yaml）", "", f"> {seed}", "",
            "---", "", "*Kamiyama Tribune / concepts.yaml より書き出し（2026-09-22）*", ""]
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser(description="概念ノートを Obsidian 用 Markdown で書き出す")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--marked", type=Path, default=MARKED_CSV)
    ap.add_argument("--mark", default="〇")
    ap.add_argument("--all", action="store_true", help="印を無視して既出全件を出す")
    args = ap.parse_args()

    concepts = yaml.safe_load((ROOT / "data" / "concepts.yaml").read_text(encoding="utf-8"))
    by_id = {c["id"]: c for c in concepts}
    name_of = {c["id"]: c["name_ja"] for c in concepts}

    hist = json.loads((ROOT / "logs" / "concept_history.json").read_text(encoding="utf-8"))
    first: dict[str, str] = {}
    for r in hist["history"]:
        cid = r["concept_id"]
        if cid not in first or r["displayed_on"] < first[cid]:
            first[cid] = r["displayed_on"]

    generated: dict[str, dict] = {}
    if UNSEEN_CSV.exists():
        with UNSEEN_CSV.open(encoding="utf-8-sig") as f:
            generated = {r["id"]: r for r in csv.DictReader(f)}

    if args.all:
        target_ids = [c["id"] for c in concepts if c["id"] in first]
    else:
        with args.marked.open(encoding="utf-8-sig") as f:
            target_ids = [r["id"] for r in csv.DictReader(f)
                          if (r.get(MARK_COLUMN) or "").strip() == args.mark]

    args.out.mkdir(parents=True, exist_ok=True)
    n_pub = n_gen = n_skip = 0
    multi = 0
    for cid in target_ids:
        concept = by_id.get(cid)
        if concept is None:
            print(f"  ! {cid} が concepts.yaml に無い。skip", file=sys.stderr)
            n_skip += 1
            continue
        day = first.get(cid)
        if cid in generated and cid not in first:
            g = generated[cid]
            paras = [p for p in re.split(r"\n{2,}", g["essay"].strip()) if p.strip()]
            rel = []
            for part in (g.get("related_notes") or "").split(" || "):
                if ": " in part:
                    a, b = part.split(": ", 1)
                    rel.append((a, b))
            rel_ids = [x for x in (g.get("related") or "").split("; ") if x]
            published = False
            n_gen += 1
        else:
            parsed = parse_page4(day, concept["name_ja"]) if day else None
            if not parsed:
                print(f"  ! {concept['name_ja']}（{day}）の第4面を読めない。skip", file=sys.stderr)
                n_skip += 1
                continue
            paras = parsed["paras"]
            rel = parsed["rel"]
            rel_ids = list(concept.get("related") or [])
            published = True
            n_pub += 1
        if len(paras) > 1:
            multi += 1
        note = build_note(concept, body_paras=paras, rel=rel, rel_ids=rel_ids,
                          day=day, published=published, name_of=name_of)
        (args.out / f"{_safe_filename(concept['name_ja'])}.md").write_text(note, encoding="utf-8")

    print(f"書き出し: {n_pub + n_gen} 本 → {args.out}/")
    print(f"  掲載済み（archive 回収）: {n_pub}")
    print(f"  未掲載（先行生成）      : {n_gen}")
    print(f"  複数段落の本文          : {multi}")
    if n_skip:
        print(f"  skip                    : {n_skip}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
