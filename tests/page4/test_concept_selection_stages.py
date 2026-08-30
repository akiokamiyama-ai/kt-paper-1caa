"""4 面概念の 3 段構え選出と概念プールの整合 (C188, 2026-08-30).

背景
----
C187 の調査で分かったこと:

  概念プール      222 件
  未出            107 件（プールの 48%）
  実効候補        162 件（＝ 222 − 直近 60 日の除外 60 件）
  うち未出 107 / 既出 約 55

旧実装は段 1（60 日除外）の後すぐ ``rng.choice`` していたため、未出と既出が
等確率で並び **毎日およそ 34% で既出を引いていた**。結果、未出が半分近く
残っているのに 2026-07-16 以降で再掲が 8 件発生していた（環世界 5/17→8/16、
SECI モデル 5/20→7/31 など）。

旧実装の「枯渇時は最古を再利用」経路は**構造的に発動しえなかった**。60 日で
表示できるのは最大 60 件で、222 件すべてが直近 60 日に出ることはないため。

C188 で 3 段構えにした:

  段 1  過去 exclusion_days 日に出たものを除外（従来どおり）
  段 2  未出を優先
  段 3  未出が尽きたら既出から選ぶ（再訪）

Tests:
  a) 未出があれば必ず未出から選ばれる
  b) 未出が尽きたら既出から選ばれる
  c) 60 日除外が両段で効いている
  d) どの段で選ばれたかが記録・出力される
  e) 概念プールの整合（related の参照先が実在、id 重複なし 等）
  f) C188 で補充した概念が入っている

Run::

    python3 -m tests.page4.test_concept_selection_stages
"""

from __future__ import annotations

import io
import random
import sys
from contextlib import redirect_stderr
from datetime import date
from pathlib import Path

import yaml

from scripts.page4 import concept_selector as cs

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


def _concept(i: str) -> dict:
    return {"id": i, "name_ja": i, "name_en": i, "domain": "d",
            "thinkers": [], "seed": "s", "related": [], "difficulty": 1}


def _pick(concepts, history, today=date(2026, 9, 1), seed=0):
    buf = io.StringIO()
    with redirect_stderr(buf):
        sel = cs.select_concept_for_today(
            today=today, concepts=concepts, history=history,
            persist=False, rng=random.Random(seed))
    return sel, buf.getvalue()


# ---------------------------------------------------------------------------
# (a) 未出優先
# ---------------------------------------------------------------------------

def test_prefers_unseen():
    concepts = [_concept(x) for x in ("a", "b", "c", "d")]
    # a,b は 100 日前に既出（60 日除外の外）→ 候補には残るが未出ではない
    hist = {"history": [
        {"concept_id": "a", "displayed_on": "2026-05-01"},
        {"concept_id": "b", "displayed_on": "2026-05-02"},
    ]}
    picks = set()
    for s in range(40):
        sel, log = _pick(concepts, hist, seed=s)
        picks.add(sel["id"])
    _check("a1 未出（c/d）からしか選ばれない", picks <= {"c", "d"}, str(sorted(picks)))
    _check("a2 未出が両方とも選ばれうる", picks == {"c", "d"}, str(sorted(picks)))
    _, log = _pick(concepts, hist)
    _check("a3 stage=unseen がログに出る", "stage=unseen" in log, log.strip()[-60:])


def test_unseen_wins_even_if_many_seen():
    concepts = [_concept(x) for x in "abcdefghij"]
    hist = {"history": [{"concept_id": x, "displayed_on": "2026-01-01"}
                        for x in "abcdefghi"]}   # j だけ未出
    for s in range(20):
        sel, _ = _pick(concepts, hist, seed=s)
        if sel["id"] != "j":
            _check("a4 未出が 1 件でもあればそれが選ばれる", False, sel["id"])
            return
    _check("a4 未出が 1 件でもあればそれが選ばれる", True, "j ×20")


# ---------------------------------------------------------------------------
# (b) 未出が尽きたら再訪
# ---------------------------------------------------------------------------

def test_revisit_when_no_unseen():
    concepts = [_concept(x) for x in ("a", "b", "c")]
    hist = {"history": [{"concept_id": x, "displayed_on": "2026-01-01"}
                        for x in ("a", "b", "c")]}
    sel, log = _pick(concepts, hist)
    _check("b1 未出ゼロなら既出から選ぶ", sel["id"] in {"a", "b", "c"}, sel["id"])
    _check("b2 stage=revisit がログに出る", "stage=revisit" in log, log.strip()[-70:])
    _check("b3 未出が尽きたことを知らせる（補充の判断材料）",
           "未出の概念が尽きました" in log)


def test_revisit_spreads():
    concepts = [_concept(x) for x in ("a", "b", "c")]
    hist = {"history": [{"concept_id": x, "displayed_on": "2026-01-01"}
                        for x in ("a", "b", "c")]}
    picks = {(_pick(concepts, hist, seed=s)[0])["id"] for s in range(30)}
    _check("b4 再訪はランダム（1 つに固定されない）", len(picks) >= 2, str(sorted(picks)))


# ---------------------------------------------------------------------------
# (c) 60 日除外
# ---------------------------------------------------------------------------

def test_exclusion_applies_to_unseen_stage():
    concepts = [_concept(x) for x in ("a", "b")]
    # b は昨日出たばかり（a は未出）
    hist = {"history": [{"concept_id": "b", "displayed_on": "2026-08-31"}]}
    for s in range(20):
        sel, _ = _pick(concepts, hist, seed=s)
        if sel["id"] != "a":
            _check("c1 直近に出たものは未出優先段でも除外される", False, sel["id"])
            return
    _check("c1 直近に出たものは未出優先段でも除外される", True, "a ×20")


def test_exclusion_applies_to_revisit_stage():
    concepts = [_concept(x) for x in ("a", "b")]
    hist = {"history": [
        {"concept_id": "a", "displayed_on": "2026-01-01"},   # 60 日超（再訪可）
        {"concept_id": "b", "displayed_on": "2026-08-31"},   # 直近（除外）
    ]}
    for s in range(20):
        sel, _ = _pick(concepts, hist, seed=s)
        if sel["id"] != "a":
            _check("c2 再訪段でも 60 日除外が効く", False, sel["id"])
            return
    _check("c2 再訪段でも 60 日除外が効く", True, "a ×20")


def test_exclusion_days_constant():
    _check("c3 EXCLUSION_DAYS は 60", cs.EXCLUSION_DAYS == 60, str(cs.EXCLUSION_DAYS))


# ---------------------------------------------------------------------------
# (d) 記録
# ---------------------------------------------------------------------------

def test_stage_recorded_in_history():
    concepts = [_concept(x) for x in ("a", "b")]
    hist = {"history": []}
    buf = io.StringIO()
    with redirect_stderr(buf):
        cs.select_concept_for_today(today=date(2026, 9, 1), concepts=concepts,
                                    history=hist, persist=False,
                                    rng=random.Random(0))
    # persist=False なので履歴には積まれない
    _check("d1 persist=False では履歴に積まない", hist["history"] == [])
    _check("d2 選出結果がログに出る", "selected=" in buf.getvalue())
    _check("d3 プール内訳がログに出る（pool/unseen/excluded）",
           all(k in buf.getvalue() for k in ("pool=", "unseen=", "excluded=")),
           buf.getvalue().strip()[-70:])


def test_ever_shown_helper():
    hist = {"history": [{"concept_id": "a", "displayed_on": "2020-01-01"},
                        {"concept_id": "b", "displayed_on": "2026-08-01"}]}
    _check("d4 _ever_shown_ids は全期間を見る",
           cs._ever_shown_ids(hist) == {"a", "b"},
           str(cs._ever_shown_ids(hist)))


# ---------------------------------------------------------------------------
# (e)(f) 概念プールの整合
# ---------------------------------------------------------------------------

def _load_pool():
    root = Path(__file__).resolve().parents[2]
    return yaml.safe_load((root / "data" / "concepts.yaml").read_text(encoding="utf-8"))


def test_pool_integrity():
    pool = _load_pool()
    ids = [c["id"] for c in pool]
    _check("e1 概念数が 267 件以上", len(pool) >= 267, str(len(pool)))
    _check("e2 id に重複がない", len(ids) == len(set(ids)),
           str(len(ids) - len(set(ids))))
    idset = set(ids)
    bad = [(c["id"], r) for c in pool for r in (c.get("related") or [])
           if r not in idset]
    _check("e3 related の参照先がすべて実在（C148 で未登録参照の前例あり）",
           not bad, str(bad[:3]))
    req = ("id", "name_ja", "name_en", "domain", "thinkers", "seed",
           "related", "difficulty")
    miss = [c.get("id") for c in pool if any(k not in c for k in req)]
    _check("e4 必須フィールドが揃っている", not miss, str(miss[:3]))
    import re
    stray = [c["id"] for c in pool
             if re.search(r"[а-яА-Я가-힯]",
                          f"{c['name_ja']}{c['seed']}{' '.join(c['thinkers'])}")]
    _check("e5 キリル文字・ハングルの混入がない", not stray, str(stray))


def test_c189_additions_present():
    """C189: C188 の抽出漏れを再走査して補充した分。

    C188 は既収録判定に **seed 本文まで含めていた**ため、seed で言及されて
    いるだけで見出しとしては存在しない概念を「既収録」と誤判定していた。
    実践知がその実例（wild_knowledge の seed に語があったため漏れた）。
    """
    pool = {c["id"]: c for c in _load_pool()}
    expected = ["phronesis", "theoria", "poiesis", "techne", "episteme",
                "metis", "legitimate_peripheral_participation", "antifragility",
                "redundancy", "public_sphere", "instrumental_reason",
                "gift_economy", "rite_of_passage", "body_schema",
                "transaction_cost", "narrative_identity", "generativity",
                "alienation"]
    missing = [i for i in expected if i not in pool]
    _check(f"f3 C189 の補充 {len(expected)} 件がすべて入っている", not missing,
           str(missing))


def test_aristotle_knowledge_types_complete():
    """アリストテレスの知の分類が見出しとして揃っていること。

    seed 内の言及だけでは足りない —— concept_writer が本文を書く対象は
    見出しのある entry だけなので、言及されるだけの概念は紙面に出ない。
    """
    pool = {c["id"]: c for c in _load_pool()}
    for cid, ja in (("theoria", "観想知"), ("phronesis", "実践知"),
                    ("poiesis", "制作知"), ("techne", "テクネー"),
                    ("episteme", "エピステーメー")):
        ok = cid in pool and ja in pool[cid]["name_ja"]
        _check(f"f4 {cid} が見出しとして存在（{ja}）", ok,
               pool.get(cid, {}).get("name_ja", "—"))
    # 相互にリンクしていること
    linked = all("phronesis" in (pool[c].get("related") or [])
                 for c in ("theoria", "techne", "episteme"))
    _check("f5 三分が phronesis と相互リンクしている", linked)


def test_c188_additions_present():
    pool = {c["id"]: c for c in _load_pool()}
    expected = ["positive_violence", "freundlichkeit", "vita_contemplativa",
                "attention_as_love", "berlin_wisdom_paradigm",
                "maintenance_studies", "broken_world_thinking", "care_ethics",
                "teire", "satoyama", "kintsugi", "quantification", "gdp",
                "goodharts_law", "legibility", "mcdonaldization",
                "intangible_heritage", "hedgehog_and_fox",
                "isaiah_berlin_pluralism", "chestertons_fence", "dwelling",
                "limited_war", "phenology", "seasonal_calendar",
                "weather_and_mood", "device_paradigm", "illegible_benefits"]
    missing = [i for i in expected if i not in pool]
    _check(f"f1 C188 の補充 {len(expected)} 件がすべて入っている", not missing,
           str(missing))
    # 双方向でなくとも、既存概念へのリンクを持っていること
    orphan = [i for i in expected if not pool[i].get("related")]
    _check("f2 補充概念がすべて related を持つ", not orphan, str(orphan))


def main() -> int:
    print("C188: 概念の 3 段構え選出と補充\n")
    print("(a) 未出優先:")
    test_prefers_unseen()
    test_unseen_wins_even_if_many_seen()
    print()
    print("(b) 未出が尽きたら再訪:")
    test_revisit_when_no_unseen()
    test_revisit_spreads()
    print()
    print("(c) 60 日除外:")
    test_exclusion_applies_to_unseen_stage()
    test_exclusion_applies_to_revisit_stage()
    test_exclusion_days_constant()
    print()
    print("(d) 記録:")
    test_stage_recorded_in_history()
    test_ever_shown_helper()
    print()
    print("(e)(f) 概念プール:")
    test_pool_integrity()
    test_c188_additions_present()
    test_c189_additions_present()
    test_aristotle_knowledge_types_complete()
    print()
    print(f"=== {PASS} passed, {FAIL} failed ===")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
