"""Unit tests for page1_v3.saturday_responder (Phase 3, 2026-05-23).

Haiku/miibo caller を mock し、ネットワーク無しで全 fallback パスを検証。

Run::

    python3 -m tests.page1_v3.test_saturday_responder
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from datetime import date

from scripts.page1_v3 import saturday_responder as sr
from scripts.page1_v3.comments_reader import DailyComment
from scripts.page1_v3.monthly_pivotal import WeekContext

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


@dataclass
class _ClaudeResp:
    text: str
    cost_usd: float = 0.003


@dataclass
class _MiiboResp:
    utterance_response: str
    raw_response: dict = None
    elapsed_ms: int = 0


def _wc_saturday() -> WeekContext:
    return WeekContext(
        week_label="W1", theme="AIと暗黙知",
        period=(date(2026, 5, 24), date(2026, 5, 30)),
        article={"title": "The Death of Tacit Knowledge",
                 "source": "Past Tense Tomorrow"},
        day_label="土", angle_key="response", angle_label_jp="応答",
    )


def _past_essays() -> list[dict]:
    days = [("2026-05-24", "全体像", "Q1"), ("2026-05-25", "批判的", "Q2"),
            ("2026-05-26", "実践者", "Q3"), ("2026-05-27", "思想家", "Q4"),
            ("2026-05-28", "歴史", "Q5"), ("2026-05-29", "統合＋問い", "Q6")]
    return [
        {"date": d, "angle_label_jp": l,
         "essay": {"daily_question": q, "essay_title": f"T-{q}", "body": f"B-{q}" * 20}}
        for d, l, q in days
    ]


def _comments(n: int = 3) -> list[DailyComment]:
    base = [
        ("2026-05-24", "日", "全体像", "日曜のコメント"),
        ("2026-05-25", "月", "批判的", "月曜の違和感メモ"),
        ("2026-05-27", "水", "思想家", "水曜の発見"),
    ][:n]
    return [
        DailyComment(target_date=date.fromisoformat(d), day_label=dl,
                     angle_label_jp=ang, body=body)
        for d, dl, ang, body in base
    ]


def _valid_miibo_json() -> str:
    return json.dumps({
        "daily_question": "AIかみやま から神山さんへ",
        "response_title": "今週の聞き取り",
        "response_body": "本文" * 200,
    }, ensure_ascii=False)


# ---------------------------------------------------------------------------
# (a) コメント 0 件 → 軽量 fallback、LLM 呼ばない
# ---------------------------------------------------------------------------

def test_empty_comments_skips_llm():
    haiku_called = [False]
    miibo_called = [False]

    def haiku_caller(*, system, user):
        haiku_called[0] = True
        return _ClaudeResp(text="x")

    def miibo_caller(*, utterance):
        miibo_called[0] = True
        return _MiiboResp(utterance_response=_valid_miibo_json())

    r = sr.generate_saturday_response(_wc_saturday(), _past_essays(), [],
                                       haiku_caller=haiku_caller,
                                       miibo_caller=miibo_caller)
    _check("a1 0 件 → 両 LLM 呼ばず", not haiku_called[0] and not miibo_called[0])
    _check("a2 is_fallback=False（軽量だが意図された休載）", r.is_fallback is False)
    _check("a3 angle_label='土曜 - 応答'", r.angle_label == "土曜 - 応答")
    _check("a4 response_title に '今週は神山さんのコメントなし'",
           "コメントなし" in r.response_title)


# ---------------------------------------------------------------------------
# (b) 成功パス：Haiku + miibo 共に成功
# ---------------------------------------------------------------------------

def test_full_success_path():
    captured = {}

    def haiku_caller(*, system, user):
        captured["digest_user"] = user
        return _ClaudeResp(text="編集済み digest 200-400 字")

    def miibo_caller(*, utterance):
        captured["utterance"] = utterance
        return _MiiboResp(utterance_response=_valid_miibo_json())

    r = sr.generate_saturday_response(_wc_saturday(), _past_essays(), _comments(),
                                       haiku_caller=haiku_caller,
                                       miibo_caller=miibo_caller)
    _check("b1 is_fallback=False", r.is_fallback is False)
    _check("b2 comments_digest = Haiku 出力",
           r.comments_digest == "編集済み digest 200-400 字")
    _check("b3 digest_used_fallback=False", r.digest_used_fallback is False)
    _check("b4 response_body は miibo 由来", "本文本文" in r.response_body)
    _check("b5 response_title 反映", r.response_title == "今週の聞き取り")
    _check("b6 daily_question 反映", r.daily_question == "AIかみやま から神山さんへ")
    _check("b7 digest_cost_usd 反映（Haiku のみ）", r.digest_cost_usd == 0.003)
    _check("b8 Haiku user に各日コメントが含まれる",
           "日曜のコメント" in captured["digest_user"]
           and "月曜の違和感メモ" in captured["digest_user"])
    _check("b9 miibo utterance に digest が含まれる",
           "編集済み digest" in captured["utterance"])
    _check("b10 miibo utterance に主軸記事タイトル",
           "The Death of Tacit Knowledge" in captured["utterance"])


# ---------------------------------------------------------------------------
# (c) Haiku 失敗 → raw concat fallback、miibo 続行
# ---------------------------------------------------------------------------

def test_haiku_exception_uses_raw_concat():
    captured = {}

    def haiku_caller(*, system, user):
        raise RuntimeError("Haiku down")

    def miibo_caller(*, utterance):
        captured["utterance"] = utterance
        return _MiiboResp(utterance_response=_valid_miibo_json())

    r = sr.generate_saturday_response(_wc_saturday(), _past_essays(), _comments(),
                                       haiku_caller=haiku_caller,
                                       miibo_caller=miibo_caller)
    _check("c1 Haiku 失敗 → is_fallback=False（miibo は成功）", r.is_fallback is False)
    _check("c2 digest_used_fallback=True", r.digest_used_fallback is True)
    _check("c3 raw concat の中に各日コメントが残る",
           "日曜のコメント" in r.comments_digest)
    _check("c4 miibo はそれでも呼ばれる（raw digest を渡す）",
           "日曜のコメント" in captured["utterance"])
    _check("c5 digest_cost_usd=0（Haiku 課金されてない）", r.digest_cost_usd == 0.0)


def test_haiku_empty_response_uses_raw_concat():
    def haiku_caller(*, system, user):
        return _ClaudeResp(text="   ")

    def miibo_caller(*, utterance):
        return _MiiboResp(utterance_response=_valid_miibo_json())

    r = sr.generate_saturday_response(_wc_saturday(), _past_essays(), _comments(),
                                       haiku_caller=haiku_caller,
                                       miibo_caller=miibo_caller)
    _check("c6 Haiku 空応答 → raw concat fallback",
           r.digest_used_fallback is True and "日曜のコメント" in r.comments_digest)


# ---------------------------------------------------------------------------
# (d) miibo 失敗 → 全体 fallback
# ---------------------------------------------------------------------------

def test_miibo_exception_fallback():
    def haiku_caller(*, system, user):
        return _ClaudeResp(text="digest")

    def miibo_caller(*, utterance):
        raise RuntimeError("miibo timeout")

    r = sr.generate_saturday_response(_wc_saturday(), _past_essays(), _comments(),
                                       haiku_caller=haiku_caller,
                                       miibo_caller=miibo_caller)
    _check("d1 miibo 失敗 → is_fallback=True", r.is_fallback is True)
    _check("d2 digest は保持（Haiku 成功分）", r.comments_digest == "digest")
    _check("d3 response_title='AIかみやま応答休載'",
           r.response_title == "AIかみやま応答休載")


def test_miibo_empty_response_fallback():
    def haiku_caller(*, system, user):
        return _ClaudeResp(text="digest")

    def miibo_caller(*, utterance):
        return _MiiboResp(utterance_response="")

    r = sr.generate_saturday_response(_wc_saturday(), _past_essays(), _comments(),
                                       haiku_caller=haiku_caller,
                                       miibo_caller=miibo_caller)
    _check("d4 miibo 空応答 → is_fallback=True", r.is_fallback is True)


# ---------------------------------------------------------------------------
# (e) miibo JSON parse 失敗 → 生応答を response_body に
# ---------------------------------------------------------------------------

def test_miibo_json_parse_fail_uses_raw_text():
    def haiku_caller(*, system, user):
        return _ClaudeResp(text="digest")

    def miibo_caller(*, utterance):
        return _MiiboResp(utterance_response="not a json but text response")

    r = sr.generate_saturday_response(_wc_saturday(), _past_essays(), _comments(),
                                       haiku_caller=haiku_caller,
                                       miibo_caller=miibo_caller)
    _check("e1 JSON parse 失敗だが生テキストあり → is_fallback=False",
           r.is_fallback is False)
    _check("e2 生テキストが response_body に",
           r.response_body == "not a json but text response")
    _check("e3 response_title='本日の応答'（固定文）", r.response_title == "本日の応答")


# ---------------------------------------------------------------------------
# (f) angle_label
# ---------------------------------------------------------------------------

def test_saturday_angle_label():
    r = sr.generate_saturday_response(_wc_saturday(), _past_essays(), [])
    _check("f1 土曜 angle_label='土曜 - 応答'", r.angle_label == "土曜 - 応答")


def main() -> int:
    print("page1_v3 — saturday_responder tests")
    print()
    print("(a) コメント 0 件 → 軽量 fallback:")
    test_empty_comments_skips_llm()
    print()
    print("(b) Haiku + miibo 成功:")
    test_full_success_path()
    print()
    print("(c) Haiku 失敗 → raw concat:")
    test_haiku_exception_uses_raw_concat()
    test_haiku_empty_response_uses_raw_concat()
    print()
    print("(d) miibo 失敗 → 全体 fallback:")
    test_miibo_exception_fallback()
    test_miibo_empty_response_fallback()
    print()
    print("(e) miibo JSON parse 失敗 → 生テキスト:")
    test_miibo_json_parse_fail_uses_raw_text()
    print()
    print("(f) angle_label:")
    test_saturday_angle_label()
    print()
    print(f"=== {PASS} passed, {FAIL} failed ===")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
