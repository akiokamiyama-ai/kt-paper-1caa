"""3社の事業定義の単一情報源化 (C197, 2026-09-10).

背景
----
2026-09-10 の W16 Day 5（木曜 practitioner）の論考で、事業内容が実態とずれて
記述された::

    ✗ 「こころみが担うケアの現場」
    ✗ 「Human Energy が関わる組織開発」
    ✗ 「人材紹介の現場」（3 社のどの事業でもない）

原因は 1 面の practitioner 指示文に事業ドメインが**別途ハードコード**されて
いて、2 面が読む config/companies_context.md と同期していなかったこと。
定義が 2 箇所にあれば、片方だけずれる。

C197 で config/companies_context.md の §0 を唯一の正とし、1 面は実行時に
そこを読んで注入するようにした。

正しい事業内容:
    こころみ（Cocolomi）          自分史作成 / 企業向け経営支援 / AI 開発支援
    ヒューマンエナジー（Human Energy）  企業向け研修（メイン）
    ウェブリポ（Web-Repo）        フランチャイズマッチングビジネス

Tests:
  a) §0 が存在し、3 社の定義を含む
  b) load_company_definitions が §0 から読める
  c) practitioner のプロンプトに定義が注入される
  d) 他の角度には注入されない
  e) 誤った語がソースに残っていない（回帰）
  f) 2 面の各社セクション切り出しが壊れていない

Run::

    python3 -m tests.test_company_definitions
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

from scripts.page1_v3.essay_generator import _build_user_message
from scripts.page1_v3.monthly_pivotal import find_week_for_date, load_monthly_pivotal
from scripts.page1_v3.prompts import (
    ANGLE_INSTRUCTIONS,
    COMPANIES_CONTEXT_PATH,
    load_company_definitions,
)
from scripts.selector.page2 import CONTEXT_HEADERS, extract_company_context

PASS = 0
FAIL = 0

ROOT = Path(__file__).resolve().parents[1]

# 3 社の正しい事業内容（config/companies_context.md §0 と一致させること）
CORRECT = [
    ("こころみ", "自分史作成"),
    ("こころみ", "AI 開発支援"),
    ("ヒューマンエナジー", "企業向け研修"),
    ("ウェブリポ", "フランチャイズマッチング"),
]

# 実態と異なるため使ってはいけない語
FORBIDDEN = ["人材紹介", "ケアの現場", "シニア対話", "こころみ（ケア"]


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


# ---------------------------------------------------------------------------
# (a) §0 が正
# ---------------------------------------------------------------------------

def test_canonical_section_exists():
    _check("a1 config/companies_context.md が存在", COMPANIES_CONTEXT_PATH.exists(),
           str(COMPANIES_CONTEXT_PATH))
    text = COMPANIES_CONTEXT_PATH.read_text(encoding="utf-8")
    _check("a2 §0 の見出しがある", "## 0. 3社の事業定義" in text)
    for company, biz in CORRECT:
        _check(f"a3 §0 に「{company}: {biz}」がある",
               company in text and biz in text)


# ---------------------------------------------------------------------------
# (b) ローダ
# ---------------------------------------------------------------------------

def test_loader():
    defs = load_company_definitions()
    for company, biz in CORRECT:
        _check(f"b1 定義ブロックに {company} / {biz}",
               company in defs and biz in defs, defs[:40])
    _check("b2 禁止語の注意書きを含む",
           any(f in defs for f in ("ケア", "組織開発", "人材紹介")),
           "LLM に「書くな」と伝えるため注意書き自体には語が出る")


def test_loader_fallback():
    """§0 が見つからなくても、空ではなく正しい定義を返すこと。

    プロンプトが空になると LLM が推測で書く。それが今回の事故の形なので、
    fallback でも必ず定義を出す。
    """
    import scripts.page1_v3.prompts as pr

    orig = pr.COMPANIES_CONTEXT_PATH
    try:
        pr.COMPANIES_CONTEXT_PATH = ROOT / "does-not-exist.md"
        defs = pr.load_company_definitions()
    finally:
        pr.COMPANIES_CONTEXT_PATH = orig
    _check("b3 ファイルが無くても定義を返す（空にしない）",
           "自分史作成" in defs and "企業向け研修" in defs, defs[:40])


# ---------------------------------------------------------------------------
# (c)(d) プロンプトへの注入
# ---------------------------------------------------------------------------

def test_placeholder_in_practitioner():
    _check("c1 practitioner に placeholder がある",
           "{{COMPANY_DEFINITIONS}}" in ANGLE_INSTRUCTIONS["practitioner"])
    for angle in ("overview", "critical", "thinker", "history", "integration"):
        _check(f"d1 {angle} には placeholder が無い",
               "{{COMPANY_DEFINITIONS}}" not in ANGLE_INSTRUCTIONS[angle])


def test_injection_end_to_end():
    m = load_monthly_pivotal()
    # W16 木曜 = practitioner（C187 の V2 マッピング）
    w = find_week_for_date(date(2026, 9, 10), m)
    if w is None:
        _check("c2 W16 木曜が引ける", False); return
    _check("c2 W16 木曜は practitioner", w.angle_key == "practitioner", w.angle_key)
    msg = _build_user_message(w, date(2026, 9, 10), past_essays=None)
    _check("c3 プロンプトに事業定義が入る", "自分史作成" in msg)
    _check("c4 placeholder が残っていない", "{{COMPANY_DEFINITIONS}}" not in msg)

    _check("c5 注入ブロックの見出しが入る", "【グループ 3 社の事業内容】" in msg)

    # 別角度には注入されない。
    # なお full_text_excerpt 末尾の【本週の編集方針】は 6 角度分をまとめて
    # 持つので、事業名そのものはどの曜日のプロンプトにも現れる。ここで見る
    # のは **ANGLE_INSTRUCTIONS 経由の注入ブロック**が入っていないこと。
    w2 = find_week_for_date(date(2026, 9, 8), m)   # 火曜 = critical
    msg2 = _build_user_message(w2, date(2026, 9, 8), past_essays=None)
    _check("d2 critical には注入ブロックが入らない",
           "【グループ 3 社の事業内容】" not in msg2)


# ---------------------------------------------------------------------------
# (e) 誤語の回帰
# ---------------------------------------------------------------------------

def test_no_stale_terms_in_week_data():
    """monthly_pivotal.json に実態と異なる事業記述が残っていないこと。"""
    blob = json.dumps(
        json.loads((ROOT / "data" / "monthly_pivotal.json").read_text(encoding="utf-8")),
        ensure_ascii=False,
    )
    for term in FORBIDDEN:
        _check(f"e1 週データに「{term}」が無い", term not in blob)


def test_no_hardcoded_domains_in_prompts():
    """1 面のプロンプトに事業ドメインをハードコードし直していないこと。"""
    src = (ROOT / "scripts" / "page1_v3" / "prompts.py").read_text(encoding="utf-8")
    i = src.find('"practitioner"')
    seg = src[i:i + 2000] if i > 0 else ""
    _check("e2 practitioner の指示文に旧ドメイン記述が無い",
           "人材紹介・組織開発・経営者支援" not in seg)


# ---------------------------------------------------------------------------
# (f) 2 面が壊れていない
# ---------------------------------------------------------------------------

def test_page2_sections_intact():
    for key in CONTEXT_HEADERS:
        sec = extract_company_context(key)
        _check(f"f1 {key} のセクションを切り出せる",
               "事業の本質" in sec and len(sec) > 200, f"{len(sec)} 字")
        _check(f"f2 {key} に §0 が混入しない", "## 0." not in sec)


def main() -> int:
    print("C197: 3社の事業定義の単一情報源化\n")
    print("(a) §0 が正:")
    test_canonical_section_exists()
    print()
    print("(b) ローダ:")
    test_loader()
    test_loader_fallback()
    print()
    print("(c)(d) プロンプトへの注入:")
    test_placeholder_in_practitioner()
    test_injection_end_to_end()
    print()
    print("(e) 誤語の回帰:")
    test_no_stale_terms_in_week_data()
    test_no_hardcoded_domains_in_prompts()
    print()
    print("(f) 2 面が壊れていない:")
    test_page2_sections_intact()
    print()
    print(f"=== {PASS} passed, {FAIL} failed ===")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
