"""1 面の角度の曜日割当 (C187, 2026-08-29).

背景
----
神山さん判断で並びを変更した::

    曜日   V2（W16 以降）              V1（W15 まで）
    日     overview     全体像         overview     全体像
    月     history      歴史的経緯      critical     批判的
    火     critical     批判的         practitioner 実践者
    水     thinker      思想家         thinker      思想家
    木     practitioner 実践者         history      歴史
    金     integration  統合＋問い      integration  統合＋問い
    土     response     応答           response     応答

意図:

* **history を月曜へ前倒し** —— 「どこから来たか」を先に知ってから批判に入る方が
  批判の解像度が上がる。V1 では月曜の批判の根拠が木曜に後から補強されていた
* **practitioner を木曜へ後ろ倒し** —— 思想家（水）の議論を経てから実践に落とす
  方が具体性が出る。V1 では火曜の実践論が水木の議論に接続されないまま終わって
  いた

W15（8/30-9/5）は既に日曜 overview で走り出しているため、週の途中で変えると
``angles_hints`` と紙面がずれる。日付境界（``ANGLE_ORDER_V2_FROM`` = 9/6 日曜）
で切り替える。

Tests:
  a) V1 / V2 の割当が正しい
  b) 境界日で切り替わる
  c) 用語解説ラベルが角度に追従する
  d) 過去日の再生成で当時の角度が復元される
  e) ANGLE_INSTRUCTIONS が新しい並びと整合している
  f) W16 / W17 の angles_hints と暫定ブロックが新しい並びになっている

Run::

    python3 -m tests.page1_v3.test_angle_order
"""

from __future__ import annotations

import json
import re
import sys
from datetime import date, timedelta
from pathlib import Path

from scripts.page1_v3.monthly_pivotal import (
    ANGLE_ORDER_V2_FROM,
    ANNOTATION_LABEL_BY_ANGLE,
    angle_for_day,
)
from scripts.page1_v3.prompts import ANGLE_INSTRUCTIONS

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


V1 = ["overview", "critical", "practitioner", "thinker", "history",
      "integration", "response"]
V2 = ["overview", "history", "critical", "thinker", "practitioner",
      "integration", "response"]


def _week_angles(sunday: date) -> list[str]:
    return [angle_for_day(sunday + timedelta(days=i))[1] for i in range(7)]


# ---------------------------------------------------------------------------
# (a)(b) 割当と境界
# ---------------------------------------------------------------------------

def test_v1_week():
    got = _week_angles(date(2026, 8, 30))          # W15 の日曜
    _check("a1 W15（〜9/5）は V1", got == V1, str(got))


def test_v2_week():
    got = _week_angles(date(2026, 9, 6))           # W16 の日曜
    _check("a2 W16（9/6〜）は V2", got == V2, str(got))


def test_boundary():
    _check("b1 境界日は 2026-09-06（日曜）",
           ANGLE_ORDER_V2_FROM == date(2026, 9, 6), str(ANGLE_ORDER_V2_FROM))
    _check("b2 境界日が日曜（週の途中で切り替わらない）",
           ANGLE_ORDER_V2_FROM.weekday() == 6)
    before = angle_for_day(ANGLE_ORDER_V2_FROM - timedelta(days=1))[1]
    on = angle_for_day(ANGLE_ORDER_V2_FROM)[1]
    _check("b3 境界前日は V1 の土曜（response）", before == "response", before)
    _check("b4 境界当日は overview", on == "overview", on)
    # 月曜で V1/V2 が分かれること
    _check("b5 9/5 週の月曜は critical",
           angle_for_day(date(2026, 8, 31))[1] == "critical")
    _check("b6 9/6 週の月曜は history",
           angle_for_day(date(2026, 9, 7))[1] == "history")


def test_v2_persists():
    got = _week_angles(date(2026, 12, 6))
    _check("b7 以降の週もずっと V2", got == V2, str(got))


# ---------------------------------------------------------------------------
# (c) 用語解説ラベル
# ---------------------------------------------------------------------------

def test_annotation_follows_angle():
    cases = [
        (date(2026, 9, 7), "history", "歴史的事象・年表"),
        (date(2026, 9, 8), "critical", "反対論者・批判者"),
        (date(2026, 9, 10), "practitioner", "関連企業・事例"),
        (date(2026, 8, 31), "critical", "反対論者・批判者"),   # V1 側
        (date(2026, 9, 3), "history", "歴史的事象・年表"),     # V1 側
    ]
    for d, angle, label in cases:
        _, key, _ = angle_for_day(d)
        ok = key == angle and ANNOTATION_LABEL_BY_ANGLE[key] == label
        _check(f"c {d} → {angle} / {label}", ok,
               f"got {key} / {ANNOTATION_LABEL_BY_ANGLE.get(key)}")


def test_day_label_matches_weekday():
    for i, jp in enumerate("日月火水木金土"):
        d = date(2026, 9, 6) + timedelta(days=i)
        _check(f"c-label {d} の曜日ラベルが「{jp}」",
               angle_for_day(d)[0] == jp, angle_for_day(d)[0])


# ---------------------------------------------------------------------------
# (d) 過去日の再生成
# ---------------------------------------------------------------------------

def test_past_regeneration_keeps_v1():
    """C174 のように過去日を作り直しても、当時の角度が復元されること。"""
    _check("d1 W14 木曜（8/27）は history のまま",
           angle_for_day(date(2026, 8, 27))[1] == "history",
           angle_for_day(date(2026, 8, 27))[1])
    _check("d2 W13 火曜（8/18）は practitioner のまま",
           angle_for_day(date(2026, 8, 18))[1] == "practitioner",
           angle_for_day(date(2026, 8, 18))[1])


# ---------------------------------------------------------------------------
# (e) ANGLE_INSTRUCTIONS の整合
# ---------------------------------------------------------------------------

def test_instructions_order():
    ov = ANGLE_INSTRUCTIONS["overview"]
    _check("e1 overview の後段リストが V2 順",
           "history / critical / thinker / practitioner" in ov)
    _check("e2 overview に V1 順が残っていない",
           "critical / practitioner / thinker / history" not in ov)
    _check("e3 critical が月曜 history を踏まえる旨を持つ",
           "history" in ANGLE_INSTRUCTIONS["critical"])
    _check("e4 practitioner が水曜 thinker を引き取る旨を持つ",
           "thinker" in ANGLE_INSTRUCTIONS["practitioner"]
           and "着地" in ANGLE_INSTRUCTIONS["practitioner"])


def test_instructions_cover_all_angles():
    for angle in V2:
        if angle == "response":
            continue
        _check(f"e5 {angle} の指示がある", bool(ANGLE_INSTRUCTIONS.get(angle)))


# ---------------------------------------------------------------------------
# (f) W16 / W17 のデータ
# ---------------------------------------------------------------------------

_LABEL2ANGLE = {
    "overview": "overview", "全体像": "overview",
    "critical": "critical", "批判的": "critical",
    "practitioner": "practitioner", "実践者": "practitioner",
    "thinker": "thinker", "思想家": "thinker",
    "history": "history", "歴史": "history", "歴史的経緯": "history",
    "integration": "integration", "統合": "integration", "統合＋問い": "integration",
}


def test_week_data_remapped():
    root = Path(__file__).resolve().parents[2]
    data = json.loads((root / "data" / "monthly_pivotal.json").read_text(encoding="utf-8"))
    expected = [("日", "overview"), ("月", "history"), ("火", "critical"),
                ("水", "thinker"), ("木", "practitioner"), ("金", "integration")]
    for week in ("W16", "W17"):
        art = data["weeks"][week]["article"]
        # 暫定ブロックの曜日と角度の対応
        got = []
        for m in re.finditer(r"^・([日月火水木金])（([^）]+)）",
                             art["full_text_excerpt"], re.M):
            got.append((m.group(1), _LABEL2ANGLE.get(m.group(2).strip())))
        _check(f"f1 {week} 暫定ブロックが V2 順", got == expected, str(got))
        # angles_hints の先頭語が角度と合っているか
        hints = art["angles_hints"]
        _check(f"f2 {week} hints.mon が歴史", hints["mon"].startswith("歴史"),
               hints["mon"][:16])
        _check(f"f3 {week} hints.tue が批判的", hints["tue"].startswith("批判的"),
               hints["tue"][:16])
        _check(f"f4 {week} hints.thu が実践者", hints["thu"].startswith("実践者"),
               hints["thu"][:16])


def test_w15_untouched():
    """W15 は V1 のまま（週の途中で変えない）。"""
    root = Path(__file__).resolve().parents[2]
    data = json.loads((root / "data" / "monthly_pivotal.json").read_text(encoding="utf-8"))
    hints = data["weeks"]["W15"]["article"]["angles_hints"]
    _check("f5 W15 hints.mon は批判的のまま", hints["mon"].startswith("批判的"),
           hints["mon"][:16])
    _check("f6 W15 hints.thu は歴史のまま", hints["thu"].startswith("歴史"),
           hints["thu"][:16])


def main() -> int:
    print("C187: 1 面の角度の曜日割当\n")
    print("(a) 割当:")
    test_v1_week()
    test_v2_week()
    print()
    print("(b) 境界:")
    test_boundary()
    test_v2_persists()
    print()
    print("(c) 用語解説ラベルの追従:")
    test_annotation_follows_angle()
    test_day_label_matches_weekday()
    print()
    print("(d) 過去日の再生成:")
    test_past_regeneration_keeps_v1()
    print()
    print("(e) ANGLE_INSTRUCTIONS:")
    test_instructions_order()
    test_instructions_cover_all_angles()
    print()
    print("(f) W16 / W17 のデータ:")
    test_week_data_remapped()
    test_w15_untouched()
    print()
    print(f"=== {PASS} passed, {FAIL} failed ===")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
