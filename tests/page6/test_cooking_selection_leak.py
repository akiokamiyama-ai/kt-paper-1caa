"""6 面料理の本文に「料理を選ぶ過程」が漏れる問題 (C216, 2026-10-07).

C178 (2026-08-20) で出力順を column_body 先行にしたところ、モデルが本文を
書きながら料理を選ぶ形になり、選定の試行錯誤が文章に出るようになった。

archive 159 日の実測:
    C178 前  0 / 110 日
    C178 後  5 /  49 日（10 月は 2 / 7）
うち 8/22 は 1 品の中の対比（そうめんではなく冷や麦）で正当な文。
本物の漏れは 9/23・9/24・10/2・10/7 の 4 件。

このテストが固めること:
* 本物の漏れ 4 件（archive の実文）を **全部検出**する
* 8/22 の正当な対比を **検出しない**（誤検知させない）
* プロンプトは「料理を決めてから本文」の順序で、禁止事項が書いてある
* 漏れがあれば **本番関数を通して** 1 回だけ再生成し、解消した方を採る
* 再生成でも直らなければ static fallback には落とさず、問題の少ない方を採る
* C178 の整合チェックは引き続き効く

Run::

    python3 -m tests.page6.test_cooking_selection_leak
"""

from __future__ import annotations

import sys
import tempfile
from datetime import date
from pathlib import Path

from scripts.page6 import cooking_generator as cg
from scripts.page6 import prompts

PASS = 0
FAIL = 0


def _check(label: str, cond: bool, detail: str = "") -> bool:
    global PASS, FAIL
    line = f"  {'✓' if cond else '✗'} {label}"
    if detail:
        line += f"  ({detail})"
    print(line)
    if cond:
        PASS += 1
    else:
        FAIL += 1
    return cond


# archive から抜いた実文（要所だけ）
REAL_LEAKS = {
    "2026-09-23": "朝市でほくほくした顔をしているのが、新里芋と並ぶ「菊芋」……ではなく、"
                  "今日の主役は中東の台所でおなじみのレンズ豆だ。",
    "2026-09-24": "売り場でひときわ存在感を放つのがごぼうの隣に並ぶ「菊芋」……ではなく、"
                  "今日はもう一つの秋の名脇役、にんじんと",
    "2026-10-02": "アドボの姉妹レシピではなく、ベトナム風の薄塩なますがけ炒め——ではなく、"
                  "今日の一品は",
    "2026-10-07": "ごつごつとした肌の里芋……ではなく、今日はその隣に並ぶ「むかご」に目を"
                  "向けてみたい。さつまいもと舞茸の組み合わせは先日済みなので、今日の主役は"
                  "秋の白菜と豆腐——ではなく、今朝の厨房が選んだのは「秋大根と油揚げの和風"
                  "薄塩煮」だ。",
}
# 正当な対比（拾ってはいけない）
LEGIT = {
    "2026-08-22": "だしをきかせた和風の冷やし浸し麺を提案したい。麺はそうめんではなく、"
                  "今回は平打ちの冷や麦で。だし昆布と薄口しょうゆ、",
    "対比": "油ではなくバターで焼くと香りが立つ。",
}


def _body(text: str) -> dict:
    return {"column_body": text}


# ---------------------------------------------------------------------------
# (a) 検知器の精度
# ---------------------------------------------------------------------------

def test_detects_all_real_leaks():
    for day, text in REAL_LEAKS.items():
        hit = cg._detect_selection_leak(_body(text))
        _check(f"a1 ★{day} の実例を検出する", bool(hit), str(hit))


def test_no_false_positive_on_legit_contrast():
    for label, text in LEGIT.items():
        hit = cg._detect_selection_leak(_body(text))
        _check(f"a2 ★{label} の正当な対比は拾わない", hit == [], str(hit))


def test_detects_each_pattern():
    _check("a3 言い淀み→却下",
           "hesitation_reject" in cg._detect_selection_leak(_body("菊芋……ではなく、")))
    _check("a4 除外リストの読み上げ",
           "exclusion_readout" in cg._detect_selection_leak(_body("舞茸は先日済みなので")))
    _check("a5 選ぶ行為の語り",
           "choosing_narration" in cg._detect_selection_leak(_body("今朝の厨房が選んだのは")))
    _check("a6 空・不正入力は空リスト",
           cg._detect_selection_leak(None) == [] and cg._detect_selection_leak({}) == [])


# ---------------------------------------------------------------------------
# (b) プロンプト
# ---------------------------------------------------------------------------

def test_prompt_order_dish_first():
    t = prompts.COOKING_USER_TEMPLATE
    _check("b1 ★出力フォーマットで dish_name が column_body より先",
           t.index('"dish_name"') < t.index('"column_body"'))
    _check("b2 C178 の「本文を最初に書く」指示は消えている",
           "column_body を最初に書く" not in t)


def test_prompt_prohibitions():
    t = prompts.COOKING_USER_TEMPLATE
    _check("b3 候補を挙げて否定しない旨がある", "候補として挙げて否定しない" in t)
    _check("b4 過去の料理に本文で触れない旨がある", "過去に提案した料理" in t)
    _check("b5 選ぶ行為を語らない旨がある", "選ぶ行為そのものを語らない" in t)
    _check("b6 正当な対比は許される旨がある（禁止しすぎない）", "冷や麦" in t)
    _check("b7 C178 の「同じ1品」の要件は残っている", "完全に同じ1品" in t)


# ---------------------------------------------------------------------------
# (c) ★本番関数を通した再生成
# ---------------------------------------------------------------------------

GOOD = ('{"dish_name": "秋大根と油揚げの和風薄塩煮", '
        '"ingredients_summary": "大根、油揚げ、だし、薄口しょうゆ", '
        '"genre": "和", "column_title": "大根の甘みを引き出す", '
        '"column_body": "秋の大根は甘みが増す。油揚げと合わせ、だしと薄口しょうゆで'
        'ことこと煮れば、大根に油揚げのコクが移る。下茹では不要で、薄く切って火の通り'
        'を揃えれば二十分ほどで仕上がる。"}')
LEAKY = ('{"dish_name": "秋大根と油揚げの和風薄塩煮", '
         '"ingredients_summary": "大根、油揚げ、だし、薄口しょうゆ", '
         '"genre": "和", "column_title": "大根の甘みを引き出す", '
         '"column_body": "里芋……ではなく、今朝の厨房が選んだのは大根だ。油揚げと'
         '合わせ、だしと薄口しょうゆで煮る。"}')


class _Resp:
    def __init__(self, text):
        self.text = text
        self.cost_usd = 0.01


def _run(responses: list[str]):
    """generate_cooking_column を本番どおり呼び、LLM だけ差し替える."""
    calls = {"n": 0}
    orig = cg.llm.call_claude_with_retry

    def fake(**kw):
        i = calls["n"]
        calls["n"] += 1
        return _Resp(responses[min(i, len(responses) - 1)])

    cg.llm.call_claude_with_retry = fake
    try:
        with tempfile.TemporaryDirectory() as td:
            out = cg.generate_cooking_column(
                target_date=date(2026, 10, 8), history={"history": []},
                persist=False, history_path=Path(td) / "h.json",
            )
    finally:
        cg.llm.call_claude_with_retry = orig
    return out, calls["n"]


def test_leak_triggers_one_retry_and_fixes():
    out, n = _run([LEAKY, GOOD])
    _check("c1 ★漏れがあれば再生成する（呼び出し 2 回）", n == 2, f"{n} 回")
    _check("c2 ★解消した方を採る",
           "ではなく" not in out["column_body"], out["column_body"][:30])
    _check("c3 static fallback に落ちない", not out.get("is_fallback"))


def test_clean_output_does_not_retry():
    _, n = _run([GOOD])
    _check("c4 ★問題が無ければ再生成しない（呼び出し 1 回）", n == 1, f"{n} 回")


def test_retry_at_most_once():
    out, n = _run([LEAKY, LEAKY, GOOD])
    _check("c5 ★再生成は 1 回まで（3 回目は呼ばない）", n == 2, f"{n} 回")
    _check("c6 直らなくても static fallback には落ちない",
           not out.get("is_fallback") and out["dish_name"] != "鮭の塩焼き定食",
           out["dish_name"])


def test_c178_consistency_still_enforced():
    """★順序を戻しても C178 の整合チェックは効く."""
    drift = ('{"dish_name": "夏ズッキーニとベーコンの洋風レモンバタースパゲッティ", '
             '"ingredients_summary": "ズッキーニ、ベーコン、スパゲッティ、レモン", '
             '"genre": "洋", "column_title": "夏の一皿", '
             '"column_body": "とうもろこしとズッキーニをバターでソテーする。'
             '甘みが引き立つ。"}')
    _, n = _run([drift, GOOD])
    _check("c7 ★料理名と本文のずれで再生成する（C178 の回帰）", n == 2, f"{n} 回")


def main() -> int:
    print("C216: 6 面料理の「選ぶ過程」の漏れ\n")
    print("(a) 検知器の精度（archive の実文）:")
    test_detects_all_real_leaks(); test_no_false_positive_on_legit_contrast()
    test_detects_each_pattern()
    print()
    print("(b) プロンプト:")
    test_prompt_order_dish_first(); test_prompt_prohibitions()
    print()
    print("(c) ★本番関数を通した再生成:")
    test_leak_triggers_one_retry_and_fixes(); test_clean_output_does_not_retry()
    test_retry_at_most_once(); test_c178_consistency_still_enforced()
    print()
    print(f"=== {PASS} passed, {FAIL} failed ===")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
