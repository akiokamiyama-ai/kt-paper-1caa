"""同日再ラン時の冪等性 (C185, 2026-08-29).

背景
----
2026-08-28 に GitHub Actions の schedule が **+8 時間遅延**し、神山さんの手動
実行（08:39 JST）の**後**に発火した（10:37 JST）::

    2026-08-27T23:39Z  workflow_dispatch  success   ← 手動（08:39 JST）
    2026-08-28T01:37Z  schedule           success   ← 遅延発火（10:37 JST）

結果、同じ日付で 2 回生成が走り:

  * archive commit が 2 本作られ、**紙面が丸ごと差し替わった**
    （朝: スピノザ / 白ワインハーブ蒸し煮 → 昼: 遺伝的アルゴリズム / 韓国風ナムル）
  * ``concept_history`` / ``cooking_history`` / ``page5_history`` に同じ日付が
    2 件記録された（いずれも ``.append()`` 実装だった）
  * ``page1_v3_history`` だけは ``save_essay`` が「同日エントリは差し替え
    （再ラン耐性）」だったため無傷

C185 で 3 つの履歴を ``save_essay`` と同じ upsert に揃え、workflow 側に二重実行
ガードを入れた。

Tests:
  a) concept_history の同日 upsert
  b) cooking_history の同日 upsert
  c) page5_history の同日 upsert
  d) 別日は共存する（upsert が日付単位であること）
  e) 既存の順序・他フィールドを壊さない
  f) workflow の二重実行ガードと force の配線

Run::

    python3 -m tests.test_rerun_idempotency
"""

from __future__ import annotations

import json
import re
import sys
import tempfile
from datetime import date
from pathlib import Path

from scripts.page6 import cooking_generator as cg
from scripts.page4 import concept_selector as cs
from scripts.selector import serendipity as sd

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


def _dates(hist: dict, key: str) -> list[str]:
    return [str(e.get(key)) for e in hist["history"]]


# ---------------------------------------------------------------------------
# (a) concept_history
# ---------------------------------------------------------------------------

def test_concept_upsert():
    h = {"history": []}
    cs._upsert_entry(h, {"concept_id": "spinoza", "name_ja": "スピノザ",
                         "displayed_on": "2026-08-28"}, date_key="displayed_on")
    cs._upsert_entry(h, {"concept_id": "genetic_algorithm", "name_ja": "遺伝的アルゴリズム",
                         "displayed_on": "2026-08-28"}, date_key="displayed_on")
    _check("a1 同日 2 回で 1 件になる", len(h["history"]) == 1, str(len(h["history"])))
    _check("a2 後勝ち（最後に書いた方が残る）",
           h["history"][0]["concept_id"] == "genetic_algorithm",
           h["history"][0]["concept_id"])


def test_concept_upsert_keeps_other_days():
    h = {"history": [{"concept_id": "a", "displayed_on": "2026-08-27"}]}
    cs._upsert_entry(h, {"concept_id": "b", "displayed_on": "2026-08-28"},
                     date_key="displayed_on")
    cs._upsert_entry(h, {"concept_id": "c", "displayed_on": "2026-08-28"},
                     date_key="displayed_on")
    _check("a3 別日は共存する",
           _dates(h, "displayed_on") == ["2026-08-27", "2026-08-28"],
           str(_dates(h, "displayed_on")))
    _check("a4 前日のエントリは無改変", h["history"][0]["concept_id"] == "a")


# ---------------------------------------------------------------------------
# (b) cooking_history
# ---------------------------------------------------------------------------

def test_cooking_upsert():
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "cooking_history.json"
        cg.append_history(dish_name="夏なすと鶏むね肉の洋風白ワインハーブ蒸し煮",
                          genre="洋", target_date=date(2026, 8, 28),
                          history={"history": []}, path=p)
        h = json.load(open(p, encoding="utf-8"))
        cg.append_history(dish_name="夏きゅうりとわかめの韓国風薄塩ナムル",
                          genre="エスニック", target_date=date(2026, 8, 28),
                          history=h, path=p)
        h = json.load(open(p, encoding="utf-8"))
    _check("b1 同日 2 回で 1 件になる", len(h["history"]) == 1, str(len(h["history"])))
    _check("b2 後勝ち", h["history"][0]["dish_name"].startswith("夏きゅうり"),
           h["history"][0]["dish_name"])
    _check("b3 genre も差し替わる", h["history"][0]["genre"] == "エスニック")


def test_cooking_keeps_other_days():
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "h.json"
        h = {"history": []}
        for d, n in ((27, "A"), (28, "B"), (28, "C"), (29, "D")):
            h = cg.append_history(dish_name=n, genre="和",
                                  target_date=date(2026, 8, d), history=h, path=p)
    _check("b4 別日は共存し、同日だけ潰れる",
           [e["dish_name"] for e in h["history"]] == ["A", "C", "D"],
           str([e["dish_name"] for e in h["history"]]))


# ---------------------------------------------------------------------------
# (c) page5_history
# ---------------------------------------------------------------------------

def test_serendipity_upsert():
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "page5_history.json"
        sd.append_history_entry({"displayed_on": "2026-08-28",
                                 "article_url": "https://x/718593"}, path=p)
        sd.append_history_entry({"displayed_on": "2026-08-28",
                                 "article_url": "https://x/718611"}, path=p)
        sd.append_history_entry({"displayed_on": "2026-08-29",
                                 "article_url": "https://x/other"}, path=p)
        h = json.load(open(p, encoding="utf-8"))
    _check("c1 同日 2 回で 1 件になる",
           len([e for e in h["history"] if e["displayed_on"] == "2026-08-28"]) == 1)
    _check("c2 後勝ち",
           h["history"][0]["article_url"].endswith("718611"),
           h["history"][0]["article_url"])
    _check("c3 別日は共存", len(h["history"]) == 2, str(len(h["history"])))


# ---------------------------------------------------------------------------
# (e) 実データ回帰: 8/28 の重複が掃除されていること
# ---------------------------------------------------------------------------

def test_real_histories_have_no_duplicates():
    root = Path(__file__).resolve().parents[1]
    spec = [("concept_history.json", "displayed_on"),
            ("cooking_history.json", "date"),
            ("page5_history.json", "displayed_on")]
    for name, key in spec:
        f = root / "logs" / name
        if not f.exists():
            _check(f"e {name} が存在", False, str(f)); continue
        hs = json.load(open(f, encoding="utf-8"))["history"]
        n = sum(1 for e in hs if str(e.get(key)) == "2026-08-28")
        _check(f"e {name} の 8/28 が 1 件", n == 1, f"{n} 件")


# ---------------------------------------------------------------------------
# (f) workflow のガード配線
# ---------------------------------------------------------------------------

def test_workflow_guard():
    wf = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "daily.yml"
    if not wf.exists():
        _check("f daily.yml が見つかる", False, str(wf)); return
    text = wf.read_text(encoding="utf-8")
    _check("f1 force input がある", "force:" in text and "workflow_dispatch:" in text)
    _check("f2 ガード step がある", "id: guard" in text)
    _check("f3 archive の存在を見ている",
           re.search(r'\[ -f "archive/\$\{DATE\}\.html" \]', text) is not None)
    _check("f4 skip したことを警告に出す（C156）",
           "::warning" in text and "C185" in text)
    for step in ("Generate Tribune", "Commit and push",
                 "Refresh index.html with today's archive"):
        i = text.find(f"- name: {step}")
        seg = text[i:i + 200]
        _check(f"f5 「{step}」がガードされている",
               "steps.guard.outputs.SKIP != 'true'" in seg)
    # 重複キーの回帰（一度踏んだ）
    blocks = re.split(r"\n(?=      - name: )", text)
    dup = [b for b in blocks if len(re.findall(r"^        if:", b, re.M)) > 1]
    _check("f6 step 内に if: が重複していない（YAML 重複キー回帰）", not dup,
           str(len(dup)))


def main() -> int:
    print("C185: 同日再ランの冪等性\n")
    print("(a) concept_history:")
    test_concept_upsert()
    test_concept_upsert_keeps_other_days()
    print()
    print("(b) cooking_history:")
    test_cooking_upsert()
    test_cooking_keeps_other_days()
    print()
    print("(c) page5_history:")
    test_serendipity_upsert()
    print()
    print("(e) 実データ回帰:")
    test_real_histories_have_no_duplicates()
    print()
    print("(f) workflow のガード:")
    test_workflow_guard()
    print()
    print(f"=== {PASS} passed, {FAIL} failed ===")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
