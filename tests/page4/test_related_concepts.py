"""Unit tests for scripts/page4/related_concepts.py (C158, Sprint 13, 2026-08-12).

Tests:
  a) build_incoming_map（逆参照グラフ）
  b) select_related: 段 1（related / outgoing）
  c) select_related: 段 2（逆参照で補完）
  d) select_related: 段 3（同 domain で補完）
  e) 決定性（同じ入力なら同じ出力）
  f) 実データ 222 概念での網羅性（全概念で MIN_RELATED 以上）
  g) _relation_source の付与

Run::

    python3 -m tests.page4.test_related_concepts
"""

from __future__ import annotations

import sys

from scripts.page4 import concept_selector, related_concepts as rc

PASS = 0
FAIL = 0


def _check(label: str, condition: bool, detail: str = "") -> bool:
    global PASS, FAIL
    sym = "✓" if condition else "✗"
    line = f"  {sym} {label}"
    if detail:
        line += f"  ({detail})"
    print(line)
    if condition:
        PASS += 1
    else:
        FAIL += 1
    return condition


def _c(cid, related=None, domain="test", name=None) -> dict:
    return {
        "id": cid,
        "name_ja": name or f"概念{cid}",
        "name_en": cid.title(),
        "domain": domain,
        "thinkers": [],
        "seed": f"{cid} の定義。二文目。",
        "related": related or [],
        "difficulty": 1,
    }


# ---------------------------------------------------------------------------
# (a) build_incoming_map
# ---------------------------------------------------------------------------

def test_incoming_map():
    cs = [_c("a", ["b", "c"]), _c("b", ["c"]), _c("c")]
    inc = rc.build_incoming_map(cs)
    _check("a1 c への逆参照は a と b", inc["c"] == {"a", "b"}, f"got {inc['c']}")
    _check("a2 b への逆参照は a のみ", inc["b"] == {"a"}, f"got {inc['b']}")
    _check("a3 a への逆参照は無し", inc.get("a", set()) == set())


def test_incoming_map_ignores_missing_id():
    cs = [{"name_ja": "id なし", "related": ["x"]}, _c("x")]
    inc = rc.build_incoming_map(cs)
    _check("a4 id を持たない concept は逆参照元にならない",
           inc.get("x", set()) == set(), f"got {inc.get('x')}")


# ---------------------------------------------------------------------------
# (b) 段 1: related（outgoing）
# ---------------------------------------------------------------------------

def test_uses_related_first():
    cs = [_c("a", ["b", "c", "d"]), _c("b"), _c("c"), _c("d"), _c("e")]
    out = rc.select_related(cs[0], cs)
    _check("b1 related の 3 件がそのまま採用される",
           [o["id"] for o in out] == ["b", "c", "d"], f"got {[o['id'] for o in out]}")
    _check("b2 _relation_source = related",
           all(o["_relation_source"] == "related" for o in out))


def test_related_order_preserved():
    """yaml の記載順を尊重する（辞書順に並べ替えない）."""
    cs = [_c("a", ["z", "m", "b"]), _c("z"), _c("m"), _c("b")]
    out = rc.select_related(cs[0], cs)
    _check("b3 related は yaml 記載順を保つ",
           [o["id"] for o in out] == ["z", "m", "b"], f"got {[o['id'] for o in out]}")


def test_limit_respected():
    cs = [_c("a", ["b", "c", "d", "e", "f"]), _c("b"), _c("c"), _c("d"), _c("e"), _c("f")]
    out = rc.select_related(cs[0], cs, limit=2)
    _check("b4 limit で打ち切る", len(out) == 2, f"got {len(out)}")


def test_self_excluded():
    cs = [_c("a", ["a", "b"]), _c("b")]
    out = rc.select_related(cs[0], cs)
    _check("b5 自分自身は関連に含めない",
           [o["id"] for o in out] == ["b"], f"got {[o['id'] for o in out]}")


def test_dangling_reference_skipped():
    cs = [_c("a", ["ghost", "b"]), _c("b")]
    out = rc.select_related(cs[0], cs)
    _check("b6 存在しない id は無視される",
           [o["id"] for o in out] == ["b"], f"got {[o['id'] for o in out]}")


# ---------------------------------------------------------------------------
# (c) 段 2: 逆参照で補完
# ---------------------------------------------------------------------------

def test_incoming_supplements():
    # a の related は 1 件だけ。b/c が a を参照している → 逆参照で補完
    cs = [_c("a", ["x"]), _c("x"), _c("b", ["a"]), _c("c", ["a"])]
    out = rc.select_related(cs[0], cs)
    ids = [o["id"] for o in out]
    srcs = {o["id"]: o["_relation_source"] for o in out}
    _check("c1 related 1 件 + 逆参照 2 件 = 3 件", len(out) == 3, f"got {ids}")
    _check("c2 x は related、b/c は incoming",
           srcs.get("x") == "related" and srcs.get("b") == "incoming"
           and srcs.get("c") == "incoming", f"got {srcs}")


def test_incoming_not_duplicated_with_related():
    """related と逆参照が重なる場合は二重に出さない."""
    cs = [_c("a", ["b"]), _c("b", ["a"]), _c("c", ["a"])]
    out = rc.select_related(cs[0], cs)
    ids = [o["id"] for o in out]
    _check("c3 b は related 側で 1 回だけ", ids.count("b") == 1, f"got {ids}")


# ---------------------------------------------------------------------------
# (d) 段 3: 同 domain で補完
# ---------------------------------------------------------------------------

def test_domain_supplements():
    cs = [_c("a", [], domain="現象学"), _c("b", [], domain="現象学"),
          _c("c", [], domain="現象学"), _c("z", [], domain="他")]
    out = rc.select_related(cs[0], cs)
    ids = {o["id"] for o in out}
    _check("d1 related も逆参照も無ければ同 domain から補完",
           ids == {"b", "c"}, f"got {ids}")
    _check("d2 _relation_source = domain",
           all(o["_relation_source"] == "domain" for o in out))
    _check("d3 別 domain は混ざらない", "z" not in ids)


def test_no_candidates_returns_empty():
    cs = [_c("solo", [], domain="孤島")]
    out = rc.select_related(cs[0], cs)
    _check("d4 候補ゼロなら空リスト（例外を投げない）", out == [], f"got {out}")


# ---------------------------------------------------------------------------
# (e) 決定性
# ---------------------------------------------------------------------------

def test_deterministic():
    cs = [_c("a", []), _c("b", ["a"]), _c("c", ["a"]), _c("d", ["a"]),
          _c("e", ["a"]), _c("f", ["a"])]
    runs = {tuple(o["id"] for o in rc.select_related(cs[0], cs)) for _ in range(5)}
    _check("e1 同じ入力なら毎回同じ関連概念（日替わりで入れ替わらない）",
           len(runs) == 1, f"got {runs}")


# ---------------------------------------------------------------------------
# (f) 実データ 222 概念での網羅性
# ---------------------------------------------------------------------------

def test_real_data_coverage():
    concepts = concept_selector.load_concepts()
    short = []
    zero = []
    for c in concepts:
        out = rc.select_related(c, concepts)
        if len(out) == 0:
            zero.append(c["id"])
        elif len(out) < rc.MIN_RELATED:
            short.append((c["id"], len(out)))
    _check(f"f1 全 {len(concepts)} 概念で関連概念が 1 件以上",
           not zero, f"0 件: {zero[:5]}")
    _check(f"f2 全 {len(concepts)} 概念で MIN_RELATED({rc.MIN_RELATED}) 件以上",
           not short, f"不足: {short[:5]}")


def test_real_data_mostly_three():
    concepts = concept_selector.load_concepts()
    n3 = sum(1 for c in concepts if len(rc.select_related(c, concepts)) >= 3)
    ratio = n3 / len(concepts)
    _check(f"f3 3 件確保できる概念が 9 割超（実測 {ratio*100:.1f}%）",
           ratio > 0.9, f"{n3}/{len(concepts)}")


def test_real_data_no_self_reference():
    concepts = concept_selector.load_concepts()
    bad = [c["id"] for c in concepts
           if c["id"] in {o["id"] for o in rc.select_related(c, concepts)}]
    _check("f4 自己参照が 1 件も無い", not bad, f"got {bad[:5]}")


# ---------------------------------------------------------------------------
# (g) 返り値の形
# ---------------------------------------------------------------------------

def test_returned_entries_have_display_fields():
    concepts = concept_selector.load_concepts()
    out = rc.select_related(concepts[0], concepts)
    need = ("id", "name_ja", "name_en", "domain", "seed", "_relation_source")
    missing = [k for k in need if any(k not in o for o in out)]
    _check("g1 紙面描画に必要なキーが揃っている", not missing, f"missing={missing}")


def test_original_concept_not_mutated():
    cs = [_c("a", ["b"]), _c("b")]
    before = dict(cs[1])
    out = rc.select_related(cs[0], cs)
    out[0]["_relation_source"] = "tampered"
    _check("g2 返り値を書き換えても元の concepts は汚れない",
           cs[1] == before, f"got {cs[1]}")


def main() -> int:
    print("related_concepts tests (C158, Sprint 13, 2026-08-12)")
    print()
    print("(a) build_incoming_map:")
    test_incoming_map()
    test_incoming_map_ignores_missing_id()
    print()
    print("(b) 段 1: related (outgoing):")
    test_uses_related_first()
    test_related_order_preserved()
    test_limit_respected()
    test_self_excluded()
    test_dangling_reference_skipped()
    print()
    print("(c) 段 2: 逆参照で補完:")
    test_incoming_supplements()
    test_incoming_not_duplicated_with_related()
    print()
    print("(d) 段 3: 同 domain で補完:")
    test_domain_supplements()
    test_no_candidates_returns_empty()
    print()
    print("(e) 決定性:")
    test_deterministic()
    print()
    print("(f) 実データ 222 概念:")
    test_real_data_coverage()
    test_real_data_mostly_three()
    test_real_data_no_self_reference()
    print()
    print("(g) 返り値の形:")
    test_returned_entries_have_display_fields()
    test_original_concept_not_mutated()
    print()
    print(f"=== {PASS} passed, {FAIL} failed ===")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
