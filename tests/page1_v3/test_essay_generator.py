"""Unit tests for page1_v3.essay_generator (Phase 3, 2026-05-23).

LLM caller を mock し、ネットワーク無しで全 fallback パスを検証。

Run::

    python3 -m tests.page1_v3.test_essay_generator
"""

from __future__ import annotations

import json
import sys
import tempfile
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from scripts.page1_v3 import essay_generator as eg
from scripts.page1_v3.monthly_pivotal import WeekContext
from scripts.page1_v3.prompts import ESSAY_SYSTEM_PROMPT

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
class _FakeResp:
    text: str
    cost_usd: float = 0.05


def _wc(day_label: str = "日", angle_key: str = "overview",
        angle_label_jp: str = "全体像") -> WeekContext:
    return WeekContext(
        week_label="W1", theme="AIと暗黙知",
        period=(date(2026, 5, 24), date(2026, 5, 30)),
        article={
            "title": "The Death of Tacit Knowledge",
            "source": "Past Tense Tomorrow",
            "author": "Mike Turner",
            "published": "2026-04-13",
            "url": "https://x/",
            "summary": "AI 時代の暗黙知について",
            "points": ["P1", "P2", "P3"],
            "key_quote": "Q",
            "key_quote_ja": "和訳 Q",
        },
        day_label=day_label, angle_key=angle_key, angle_label_jp=angle_label_jp,
    )


def _valid_json(daily_q="日替わりの問い", title="論考タイトル",
                body="本文" * 50, ann_label="主要キーワード",
                ann_body="解説本文", quote="引用本文") -> str:
    return json.dumps({
        "daily_question": daily_q,
        "essay_title": title,
        "body": body,
        "annotation_label": ann_label,
        "annotation_body": ann_body,
        "quote_excerpt": quote,
    }, ensure_ascii=False)


# ---------------------------------------------------------------------------
# (a) 成功パス
# ---------------------------------------------------------------------------

def test_success_returns_essay_result():
    captured = {}

    def fake(*, system, user):
        captured["system"] = system
        captured["user"] = user
        return _FakeResp(text=_valid_json())

    r = eg.generate_essay(_wc(), date(2026, 5, 24), llm_caller=fake)
    _check("a1 成功 → EssayResult", isinstance(r, eg.EssayResult))
    _check("a2 is_fallback=False", r.is_fallback is False)
    _check("a3 angle_label='日曜 - 全体像'", r.angle_label == "日曜 - 全体像",
           f"got {r.angle_label!r}")
    _check("a4 daily_question 反映", r.daily_question == "日替わりの問い")
    _check("a5 cost_usd 反映", r.cost_usd == 0.05)
    _check("a6 system に ESSAY_SYSTEM_PROMPT",
           "Kamiyama Tribune の論考編集者" in captured["system"])
    _check("a7 user に主軸記事タイトル",
           "The Death of Tacit Knowledge" in captured["user"])
    _check("a8 user に角度指示（全体像）",
           "全体像" in captured["user"] and "主要キーワード" in captured["user"])


# ---------------------------------------------------------------------------
# (b) 過去日論考が user に組み込まれる
# ---------------------------------------------------------------------------

def test_past_essays_in_user_message():
    captured = {}

    def fake(*, system, user):
        captured["user"] = user
        return _FakeResp(text=_valid_json())

    past = [{
        "date": "2026-05-24", "angle_label_jp": "全体像",
        "essay": {"essay_title": "T1", "daily_question": "Q1", "body": "B1" * 100},
    }]
    eg.generate_essay(_wc(day_label="月", angle_key="critical",
                          angle_label_jp="批判的"),
                       date(2026, 5, 25), past_essays=past, llm_caller=fake)
    _check("b1 user に過去日論考の問いが含まれる", "Q1" in captured["user"])
    _check("b2 user に過去日論考のタイトルが含まれる", "T1" in captured["user"])
    _check("b3 user に過去日の角度ラベル", "全体像" in captured["user"])


def test_no_past_essays_placeholder():
    captured = {}

    def fake(*, system, user):
        captured["user"] = user
        return _FakeResp(text=_valid_json())

    eg.generate_essay(_wc(), date(2026, 5, 24), past_essays=None, llm_caller=fake)
    _check("b4 過去日無し → placeholder",
           "今週の初日" in captured["user"] or "過去日論考なし" in captured["user"])


# ---------------------------------------------------------------------------
# (c) fallback パス
# ---------------------------------------------------------------------------

def test_llm_exception_returns_fallback():
    def boom(*, system, user):
        raise RuntimeError("API 504")

    r = eg.generate_essay(_wc(), date(2026, 5, 24), llm_caller=boom)
    _check("c1 LLM 例外 → fallback", r.is_fallback is True)
    _check("c2 fallback でも angle_label は埋まる", r.angle_label == "日曜 - 全体像")
    _check("c3 fallback で quote_excerpt に key_quote_ja",
           r.quote_excerpt == "和訳 Q")


def test_json_parse_failure_returns_fallback():
    def fake(*, system, user):
        return _FakeResp(text="not a json response at all")

    with tempfile.TemporaryDirectory() as td:
        r = eg.generate_essay(_wc(), date(2026, 5, 24), llm_caller=fake,
                              fallback_raw_dir=Path(td))
    _check("c4 JSON parse 失敗 → fallback", r.is_fallback is True)


def test_missing_required_field_returns_fallback():
    def fake(*, system, user):
        # body 欠落
        return _FakeResp(text=json.dumps({
            "daily_question": "x", "essay_title": "x",
            "annotation_label": "x", "annotation_body": "x", "quote_excerpt": "x",
        }))

    with tempfile.TemporaryDirectory() as td:
        r = eg.generate_essay(_wc(), date(2026, 5, 24), llm_caller=fake,
                              fallback_raw_dir=Path(td))
    _check("c5 必須フィールド欠落 → fallback", r.is_fallback is True)


def test_empty_field_returns_fallback():
    def fake(*, system, user):
        return _FakeResp(text=json.dumps({
            "daily_question": "x", "essay_title": "x", "body": "   ",
            "annotation_label": "x", "annotation_body": "x", "quote_excerpt": "x",
        }))

    with tempfile.TemporaryDirectory() as td:
        r = eg.generate_essay(_wc(), date(2026, 5, 24), llm_caller=fake,
                              fallback_raw_dir=Path(td))
    _check("c6 空文字フィールド → fallback", r.is_fallback is True)


# ---------------------------------------------------------------------------
# (d) JSON が code fence で囲まれていても parse
# ---------------------------------------------------------------------------

def test_code_fence_stripped():
    def fake(*, system, user):
        return _FakeResp(text=f"```json\n{_valid_json()}\n```")

    r = eg.generate_essay(_wc(), date(2026, 5, 24), llm_caller=fake)
    _check("d1 ```json``` fence 付き → parse 成功", r.is_fallback is False)


def test_extra_prose_around_json():
    def fake(*, system, user):
        return _FakeResp(text=f"こちらが出力です：\n{_valid_json()}\n以上。")

    r = eg.generate_essay(_wc(), date(2026, 5, 24), llm_caller=fake)
    _check("d2 前後にテキストあり → JSON 部分のみ parse", r.is_fallback is False)


# ---------------------------------------------------------------------------
# (e) 6 角度の angle_label_text 整形
# ---------------------------------------------------------------------------

def test_angle_label_each_day():
    expected = [
        ("日", "全体像", "日曜 - 全体像"),
        ("月", "批判的", "月曜 - 批判的"),
        ("火", "実践者", "火曜 - 実践者"),
        ("水", "思想家", "水曜 - 思想家"),
        ("木", "歴史", "木曜 - 歴史"),
        ("金", "統合＋問い", "金曜 - 統合＋問い"),
    ]
    for day, label, exp in expected:
        wc = _wc(day_label=day, angle_key="overview", angle_label_jp=label)
        _check(f"e {day} → '{exp}'", eg._angle_label_text(wc) == exp)


# ---------------------------------------------------------------------------
# (f) C24 強化: parse 失敗時の 1 回 retry
# ---------------------------------------------------------------------------

def test_retry_succeeds_on_second_attempt():
    """1 回目 garbage、2 回目 valid → retry が効いて成功."""
    call_count = [0]

    def fake(*, system, user):
        call_count[0] += 1
        if call_count[0] == 1:
            return _FakeResp(text="garbage no json", cost_usd=0.04)
        return _FakeResp(text=_valid_json(), cost_usd=0.06)

    r = eg.generate_essay(_wc(), date(2026, 5, 24), llm_caller=fake)
    _check("f1 retry 成功 → is_fallback=False", r.is_fallback is False)
    _check("f2 caller が 2 回呼ばれる", call_count[0] == 2,
           f"got {call_count[0]}")
    _check("f3 cost が両 call 合算", abs(r.cost_usd - 0.10) < 1e-6,
           f"got {r.cost_usd}")


def test_retry_both_fail_returns_fallback():
    """1 回目・2 回目とも parse 失敗 → fallback、両 attempt 計上."""
    call_count = [0]

    def fake(*, system, user):
        call_count[0] += 1
        return _FakeResp(text=f"garbage attempt {call_count[0]}")

    with tempfile.TemporaryDirectory() as td:
        r = eg.generate_essay(_wc(), date(2026, 5, 24), llm_caller=fake,
                              fallback_raw_dir=Path(td))
    _check("f4 両方失敗 → fallback", r.is_fallback is True)
    _check("f5 caller が 2 回呼ばれる", call_count[0] == 2)


def test_retry_call_exception_no_double_retry():
    """1 回目 parse 失敗 → 2 回目で API 例外 → fallback（3 回目はない）."""
    call_count = [0]

    def fake(*, system, user):
        call_count[0] += 1
        if call_count[0] == 1:
            return _FakeResp(text="not json")
        raise RuntimeError("API down on retry")

    with tempfile.TemporaryDirectory() as td:
        r = eg.generate_essay(_wc(), date(2026, 5, 24), llm_caller=fake,
                              fallback_raw_dir=Path(td))
    _check("f6 retry 例外 → fallback", r.is_fallback is True)
    _check("f7 caller は 2 回のみ（3 回目なし）", call_count[0] == 2)


def test_first_attempt_exception_skips_retry():
    """1 回目で API 例外 → retry なしで即 fallback（既存挙動維持）."""
    call_count = [0]

    def fake(*, system, user):
        call_count[0] += 1
        raise RuntimeError("API down on first")

    with tempfile.TemporaryDirectory() as td:
        r = eg.generate_essay(_wc(), date(2026, 5, 24), llm_caller=fake,
                              fallback_raw_dir=Path(td))
    _check("f8 1 回目で例外 → retry せず fallback", r.is_fallback is True)
    _check("f9 caller は 1 回のみ", call_count[0] == 1)


# ---------------------------------------------------------------------------
# (g) C24 観測強化: fallback 時の raw response 保存
# ---------------------------------------------------------------------------

def test_fallback_saves_raw_response_file():
    """両 attempt 失敗時に raw が ファイルに保存される（C24 観測強化）."""
    def fake(*, system, user):
        return _FakeResp(text="garbage that is not valid json at all")

    with tempfile.TemporaryDirectory() as td:
        eg.generate_essay(_wc(), date(2026, 5, 24), llm_caller=fake,
                          fallback_raw_dir=Path(td))
        files = sorted(Path(td).glob("page1_v3_fallback_raw_*.txt"))
        has_file = len(files) == 1
        content = files[0].read_text(encoding="utf-8") if has_file else ""

    _check("g1 raw が ファイルに保存される", has_file,
           f"got {[f.name for f in files] if not has_file else 'OK'}")
    _check("g2 ファイル名に対象日付", "2026-05-24" in (files[0].name if has_file else ""))
    _check("g3 両 attempt の raw が含まれる",
           "attempt 1" in content and "attempt 2" in content)
    _check("g4 raw 内容が含まれる", "garbage that is not valid" in content)


def test_call_exception_does_not_save_raw():
    """1 回目で例外 → raw は無いのでファイルも作らない."""
    def fake(*, system, user):
        raise RuntimeError("network down")

    with tempfile.TemporaryDirectory() as td:
        eg.generate_essay(_wc(), date(2026, 5, 24), llm_caller=fake,
                          fallback_raw_dir=Path(td))
        files = list(Path(td).glob("page1_v3_fallback_raw_*.txt"))

    _check("g5 1 回目例外 → raw ファイルなし（保存内容ゼロ）", files == [])


def test_retry_call_exception_saves_first_raw():
    """1 回目 parse 失敗の raw + 2 回目例外 → 1 回目の raw が保存される."""
    call_count = [0]

    def fake(*, system, user):
        call_count[0] += 1
        if call_count[0] == 1:
            return _FakeResp(text="first attempt garbage")
        raise RuntimeError("retry network down")

    with tempfile.TemporaryDirectory() as td:
        eg.generate_essay(_wc(), date(2026, 5, 24), llm_caller=fake,
                          fallback_raw_dir=Path(td))
        files = list(Path(td).glob("page1_v3_fallback_raw_*.txt"))
        content = files[0].read_text(encoding="utf-8") if files else ""

    _check("g6 retry 例外時も 1 回目 raw は保存", len(files) == 1)
    _check("g7 1 回目の garbage が含まれる",
           "first attempt garbage" in content)


# ---------------------------------------------------------------------------
# (h) C24 プロンプト強化: 1500 字以下厳守 + JSON エスケープ
# ---------------------------------------------------------------------------

def test_prompt_includes_1500_char_strict_limit():
    """ESSAY_SYSTEM_PROMPT に「1500 字以下厳守」が含まれる."""
    _check("h1 prompt に '1500' を含む",
           "1500" in ESSAY_SYSTEM_PROMPT)
    _check("h2 prompt に '厳守' を含む",
           "厳守" in ESSAY_SYSTEM_PROMPT)
    _check("h3 body 字数厳守の文脈で言及",
           "1500 字以下" in ESSAY_SYSTEM_PROMPT
           or "1500字以下" in ESSAY_SYSTEM_PROMPT)


def test_prompt_includes_json_escape_instruction():
    """ESSAY_SYSTEM_PROMPT に JSON エスケープ指示が含まれる."""
    _check("h4 prompt に 'JSON' 厳守の文脈",
           "JSON 出力" in ESSAY_SYSTEM_PROMPT)
    _check("h5 prompt に '\\n' エスケープ指示",
           r"\n" in ESSAY_SYSTEM_PROMPT)
    _check("h6 prompt に '\\\"' エスケープ指示",
           '\\"' in ESSAY_SYSTEM_PROMPT)
    _check("h7 prompt に '生の改行' or '制御文字' 禁止指示",
           "生の改行" in ESSAY_SYSTEM_PROMPT
           or "制御文字" in ESSAY_SYSTEM_PROMPT)


def main() -> int:
    print("page1_v3 — essay_generator tests")
    print()
    print("(a) 成功パス:")
    test_success_returns_essay_result()
    print()
    print("(b) 過去日論考の組み込み:")
    test_past_essays_in_user_message()
    test_no_past_essays_placeholder()
    print()
    print("(c) fallback パス:")
    test_llm_exception_returns_fallback()
    test_json_parse_failure_returns_fallback()
    test_missing_required_field_returns_fallback()
    test_empty_field_returns_fallback()
    print()
    print("(d) JSON parse の頑健性:")
    test_code_fence_stripped()
    test_extra_prose_around_json()
    print()
    print("(e) angle_label 整形:")
    test_angle_label_each_day()
    print()
    print("(f) C24: parse 失敗時の 1 回 retry:")
    test_retry_succeeds_on_second_attempt()
    test_retry_both_fail_returns_fallback()
    test_retry_call_exception_no_double_retry()
    test_first_attempt_exception_skips_retry()
    print()
    print("(g) C24: fallback 時の raw response 保存:")
    test_fallback_saves_raw_response_file()
    test_call_exception_does_not_save_raw()
    test_retry_call_exception_saves_first_raw()
    print()
    print("(h) C24: プロンプト強化（1500 字以下厳守 + JSON エスケープ）:")
    test_prompt_includes_1500_char_strict_limit()
    test_prompt_includes_json_escape_instruction()
    print()
    print(f"=== {PASS} passed, {FAIL} failed ===")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
