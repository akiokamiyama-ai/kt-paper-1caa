"""6面料理のフィールド間整合チェック (C178, 2026-08-20).

背景
----
2026-08-20 の 6 面で、料理名／材料と本文が**別の料理**を指していた::

    表題   夏の食卓に、黄色い実の静かな主役          ← 本文と一致
    料理名 夏ズッキーニとベーコンの洋風レモンバタースパゲッティ
    材料   ズッキーニ、ベーコン、レモン、バター、スパゲッティ
    本文   とうもろこしとズッキーニのバターソテー
           （ベーコン・スパゲッティは一度も出てこない）

C177 の調査で判明したこと:

  * 生成は **1 回の JSON 応答**で 5 フィールド全部。``parsed["dish_name"]`` の
    ように直接キー参照しており、パース時の取り違えは構造上ありえない
  * ``_validate`` は存在チェックと genre 白名単のみで、フィールド間の整合を
    一切見ていなかった
  * 前日 8/19 がとうもろこしの料理。本文は前日の食材に引っ張られており、
    dish_name だけが 30 日制約を満たしていた
  * 出力順が dish_name → … → column_body で、料理名の確定と本文執筆の間に
    3 フィールド挟まる構造だった

判定対象は ``ingredients_summary`` のみ。料理名も見る案は試したが、日本語の
「と」で分割すると **「とうもろこし」が割れる**ため誤検知源になる。材料欄は
カンマ区切りで曖昧さがない。実測 115 日で 0 件:88 / 1 件:22 / 2 件:1（= 8/20）
と完全に分離できたので、閾値は 2 件（発火率 0.9%、誤検知ゼロ）。

対処は 2 本立て（C176 と同じ形）:
  1. プロンプトで column_body を先に書かせ、そこから dish_name を導出させる
  2. 整合チェックを入れ、閾値超えで 1 回だけ再生成する

Tests:
  a) 表記ゆれを吸収する（誤検知しない）
  b) 8/20 の実データで検知する
  c) 表記ゆれだった過去日（5/27・6/19）では発火しない
  d) 閾値と発火率
  e) 再生成 → 成功 / 失敗時の挙動
  f) 検知・再生成・諦めが必ず記録される（C156）
  g) プロンプトが本文先行と一致ルールを指示している

Run::

    python3 -m tests.page6.test_cooking_consistency
"""

from __future__ import annotations

import io
import json
import sys
from contextlib import redirect_stderr
from dataclasses import dataclass
from datetime import date

from scripts.page6 import cooking_generator as cg
from scripts.page6.prompts import COOKING_SYSTEM, COOKING_USER_TEMPLATE

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


# --- 2026-08-20 の実データ ---------------------------------------------------

_REAL_0820 = {
    "dish_name": "夏ズッキーニとベーコンの洋風レモンバタースパゲッティ",
    "ingredients_summary": "ズッキーニ、ベーコン、レモン、バター、スパゲッティ",
    "genre": "洋",
    "column_title": "夏の食卓に、黄色い実の静かな主役",
    "column_body": (
        "8月のとうもろこしを生のまま包丁で削ぎ落とすと、粒がぱらぱらと転がって、"
        "台所にほんのり甘い香りが広がる。今日はその粒を主役に、洋風のコーンと"
        "ズッキーニのバターソテーを提案したい。フライパンにバターをひき、薄切りの"
        "ズッキーニを並べたら中火でじっくり。焼き色がついたところでコーンを加え、"
        "白ワイン少々をまわしかけて蒸らす。仕上げは塩ひとつまみとレモン汁数滴だけ。"
        "素材の甘みを引き立てる薄味の仕上がりが、盛夏の朝の食欲にも静かに寄り添って"
        "くれる。調理時間はゆうに20分を切る。"
    ),
}

# --- 表記ゆれだが整合している過去日 -----------------------------------------

_REAL_0619 = {
    "dish_name": "夏ゴーヤと豚こまの白だし塩麹炒め",
    "ingredients_summary": "ゴーヤ、豚こま切れ、塩麹、白だし",
    "genre": "和",
    "column_title": "ゴーヤの苦みは、夏の先生",
    "column_body": (
        "ゴーヤの苦みは「アク」ではなく「個性」だと思うと、俄然親しみがわいてくる。"
        "今回は塩麹と白だしを合わせた薄味の炒めもので、その個性を穏やかに引き受ける。"
        "塩麹はゴーヤの苦みを角が取れた旨みに変えてくれる不思議な調味料で、豚肉も"
        "しっとりと仕上がる。コツはゴーヤを薄めにスライスして塩もみし、水気を"
        "しっかり絞ること。白だしは最後にひと回しするだけ。調理は10分ほど。"
    ),
}

_REAL_0527 = {
    "dish_name": "新玉ねぎとチキンのインドネシア風薄味ナシゴレン",
    "ingredients_summary": "ご飯、鶏もも肉、新玉ねぎ、ケチャップマニス",
    "genre": "エスニック",
    "column_title": "焦がし醤油の香りが誘うジャワの朝",
    "column_body": (
        "インドネシアの朝食の定番、ナシゴレンは「炒めご飯」を意味する。家庭で"
        "再現するときの鍵はケチャップマニス——ヤシ糖を使ったとろりと甘い"
        "インドネシア産の濃口醤油だ。今回は5月の新玉ねぎを粗みじんに刻んで加える"
        "ことで、みずみずしい甘みと軽い食感をプラス。火力を強めにして短時間で"
        "炒めると、余分な水気が飛んでご飯がパラリと仕上がる。"
    ),
}

_GOOD = {
    "dish_name": "夏ズッキーニととうもろこしの洋風バターソテー",
    "ingredients_summary": "ズッキーニ、とうもろこし、バター、白ワイン",
    "genre": "洋",
    "column_title": "夏の食卓に、黄色い実の静かな主役",
    "column_body": _REAL_0820["column_body"],
}


@dataclass
class _FakeResp:
    text: str
    cost_usd: float = 0.02


def _caller(*payloads):
    """呼ばれるたびに payloads を順に返す fake。"""
    seq = list(payloads)
    calls = {"n": 0}

    def fake(**kwargs):
        calls["n"] += 1
        p = seq[min(calls["n"] - 1, len(seq) - 1)]
        return _FakeResp(text=p if isinstance(p, str) else json.dumps(p))

    fake.calls = calls
    return fake


# ---------------------------------------------------------------------------
# (a) 表記ゆれの吸収
# ---------------------------------------------------------------------------

def test_appears_in_body_variants():
    """表記ゆれの吸収は 2 層構造。

    マッチャ（``_appears_in_body``）が吸収するのは、材料名の過半が本文に
    そのまま出てくる**軽い**ゆれだけ。「絹ごし豆腐」対本文「豆腐」（2/5）や
    「豚こま切れ」対「豚肉」（1/5）のような**重い**ゆれは取りこぼす。

    それで構わない。実測 115 日でこの取りこぼしは常に 1 日あたり 1 件以内に
    収まっており、閾値 2 件が二層目として吸収する。マッチャを緩めると本物の
    不整合（8/20 の「ベーコン」）まで通ってしまう。
    """
    body = "夏のトマトとなすを豆腐と一緒に。豚肉も加える。卵でとじる。"
    cases = [
        ("夏トマト", True, "修飾語つき → 本文『トマト』で一致（3/4）"),
        ("なす", True, "そのまま一致"),
        ("卵", True, "1 文字材料"),
        ("絹ごし豆腐", False, "『豆腐』は 2/5 で閾値未満 → 閾値側で吸収する"),
        ("豚こま切れ", False, "『豚』は 1/5 → 同上"),
        ("ベーコン", False, "本当に無い"),
        ("スパゲッティ", False, "本当に無い"),
        ("パクチー（なくても可）", False, "括弧は除去して判定"),
    ]
    for term, want, why in cases:
        got = cg._appears_in_body(term, body)
        _check(f"a: {term} → {got}（{why}）", got == want, f"expected {want}")


# ---------------------------------------------------------------------------
# (b)(c) 実データ
# ---------------------------------------------------------------------------

def test_detects_real_0820():
    missing = cg._missing_terms(_REAL_0820)
    _check("b1 8/20 の実データで不整合を検知",
           len(missing) >= cg.CONSISTENCY_MISSING_THRESHOLD,
           f"未出現 {len(missing)} 件: {missing}")
    _check("b2 ベーコンとスパゲッティが検出される",
           missing == ["ベーコン", "スパゲッティ"], str(missing))


def test_no_false_positive_on_real_days():
    for label, data in (("6/19 ゴーヤ", _REAL_0619), ("5/27 ナシゴレン", _REAL_0527)):
        missing = cg._missing_terms(data)
        _check(f"c: {label} は発火しない（表記ゆれ）",
               len(missing) < cg.CONSISTENCY_MISSING_THRESHOLD,
               f"未出現 {len(missing)} 件: {missing}")


def test_consistent_payload_clean():
    _check("c3 整合した payload は未出現ゼロ",
           cg._missing_terms(_GOOD) == [], str(cg._missing_terms(_GOOD)))


# ---------------------------------------------------------------------------
# (d) 閾値
# ---------------------------------------------------------------------------

def test_dish_name_not_tokenized():
    """料理名は判定に使わない（「とうもろこし」が「と」で割れる回帰）."""
    payload = {
        "column_body": "とうもろこしとズッキーニのバターソテー。バターで炒める。",
        "ingredients_summary": "とうもろこし、ズッキーニ、バター",
        "dish_name": "夏ズッキーニととうもろこしの洋風バターソテー",
    }
    _check("d0 「とうもろこし」を含む料理名で誤検知しない",
           cg._missing_terms(payload) == [], str(cg._missing_terms(payload)))


def test_threshold_value():
    _check("d1 閾値は 2 件（実測発火率 0.9%、誤検知ゼロ）",
           cg.CONSISTENCY_MISSING_THRESHOLD == 2,
           str(cg.CONSISTENCY_MISSING_THRESHOLD))
    _check("d2 一致比率は 0.5", cg.CONSISTENCY_MATCH_RATIO == 0.5)


def test_empty_body_no_crash():
    _check("d3 本文が空でも落ちない",
           cg._missing_terms({"column_body": "", "dish_name": "x",
                              "ingredients_summary": "y"}) == [])


# ---------------------------------------------------------------------------
# (e)(f) 再生成の挙動と記録
# ---------------------------------------------------------------------------

def _run(monkey_payloads):
    fake = _caller(*monkey_payloads)
    orig = cg.llm.call_claude_with_retry
    cg.llm.call_claude_with_retry = fake
    buf = io.StringIO()
    try:
        with redirect_stderr(buf):
            r = cg.generate_cooking_column(
                target_date=date(2026, 8, 20), history={"history": []},
                persist=False,
            )
    finally:
        cg.llm.call_claude_with_retry = orig
    return r, buf.getvalue(), fake.calls["n"]


def test_retry_recovers():
    r, log, n = _run([_REAL_0820, _GOOD])
    _check("e1 不整合 → 再生成が走る（LLM 2 回）", n == 2, f"calls={n}")
    _check("e2 再生成の結果を採用する",
           r["dish_name"] == _GOOD["dish_name"], r["dish_name"])
    _check("e3 static_fallback には落ちない", r["is_fallback"] is False)
    _check("f1 検知が WARN に出る", "不整合を検知" in log)
    _check("f2 再生成の成功が記録される", "再生成で整合しました" in log, log.strip()[-90:])
    _check("e4 コストが合算される", r["cost_usd"] > 0.02, str(r["cost_usd"]))


def test_retry_also_inconsistent_keeps_best():
    r, log, n = _run([_REAL_0820, _REAL_0820])
    _check("e5 再生成も不整合なら採用して続行", r["is_fallback"] is False)
    _check("e6 static_fallback に落ちない（表示上の瑕疵で紙面は成立）",
           r["dish_name"] != "鮭の塩焼き定食", r["dish_name"])
    _check("f3 諦めたことが WARN に出る", "再生成も不整合" in log, log.strip()[-90:])


def test_retry_invalid_falls_back_to_first():
    r, log, n = _run([_REAL_0820, "not json at all"])
    _check("e7 再生成が invalid なら初回を採用",
           r["dish_name"] == _REAL_0820["dish_name"], r["dish_name"])
    _check("f4 再生成 invalid が記録される", "再生成が invalid" in log,
           log.strip()[-90:])


def test_no_retry_when_consistent():
    r, log, n = _run([_GOOD])
    _check("e8 整合していれば再生成しない（LLM 1 回）", n == 1, f"calls={n}")
    _check("f5 整合時は WARN を出さない", "不整合を検知" not in log)


def test_below_threshold_logged_as_debug():
    payload = dict(_GOOD)
    payload["ingredients_summary"] = "ズッキーニ、とうもろこし、バター、ナンプラー"  # 1 件だけ欠く
    r, log, n = _run([payload])
    _check("f6 閾値未満は debug に残る（閾値の妥当性検証用）",
           "debug" in log and "本文に出てこない要素" in log, log.strip()[:100])
    _check("e9 閾値未満では再生成しない", n == 1, f"calls={n}")


# ---------------------------------------------------------------------------
# (g) プロンプト
# ---------------------------------------------------------------------------

def test_prompt_body_first():
    t = COOKING_USER_TEMPLATE
    i_body = t.find('"column_body"')
    i_dish = t.find('"dish_name"')
    _check("g1 出力スキーマで column_body が dish_name より先",
           0 <= i_body < i_dish, f"body={i_body}, dish={i_dish}")
    _check("g2 本文先行を明示している", "column_body を最初に書くこと" in t)
    _check("g3 フィールド一致ルールの節がある", "フィールド間の一致" in t)
    _check("g4 完全に同一の料理を要求している", "完全に同一の料理" in t)
    _check("g5 8/20 の実例が ×/○ で載っている",
           "スパゲッティ" in t and "とうもろこし" in t and "×" in t and "○" in t)
    _check("g6 本文を書いたあとで料理名だけ差し替える禁止を明示",
           "料理名だけ差し替えて" in t)
    _check("g7 COOKING_SYSTEM 側は従来どおり（嗜好・ジャンル）",
           "薄味" in COOKING_SYSTEM)


def main() -> int:
    print("C178: 6面料理のフィールド間整合\n")
    print("(a) 表記ゆれの吸収:")
    test_appears_in_body_variants()
    print()
    print("(b) 8/20 実データの検知:")
    test_detects_real_0820()
    print()
    print("(c) 誤検知しないこと:")
    test_no_false_positive_on_real_days()
    test_consistent_payload_clean()
    print()
    print("(d) 閾値:")
    test_dish_name_not_tokenized()
    test_threshold_value()
    test_empty_body_no_crash()
    print()
    print("(e)(f) 再生成と記録:")
    test_retry_recovers()
    test_retry_also_inconsistent_keeps_best()
    test_retry_invalid_falls_back_to_first()
    test_no_retry_when_consistent()
    test_below_threshold_logged_as_debug()
    print()
    print("(g) プロンプト:")
    test_prompt_body_first()
    print()
    print(f"=== {PASS} passed, {FAIL} failed ===")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
