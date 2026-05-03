"""Unit tests for scripts/page6/cooking_generator.py.

Run::

    python3 -m tests.page6.test_cooking_generator
"""

from __future__ import annotations

import json
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

from scripts.lib import llm
from scripts.page6 import cooking_generator

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


def _make_response(text: str, cost: float = 0.05) -> llm.ClaudeResponse:
    return llm.ClaudeResponse(
        text=text, model="stub",
        input_tokens=100, output_tokens=400,
        cache_creation_tokens=0, cache_read_tokens=0,
        cost_usd=cost,
        stop_reason="end_turn", raw_id="stub",
    )


class _StubLLM:
    def __init__(self, *, text=None, raise_exc=None, cost=0.05):
        self.text = text
        self.raise_exc = raise_exc
        self.cost = cost
        self.calls: list[dict] = []
        self._original = None

    def __enter__(self):
        self._original = llm.call_claude_with_retry

        def _stub(**kwargs):
            self.calls.append(kwargs)
            if self.raise_exc is not None:
                raise self.raise_exc
            return _make_response(self.text or "", cost=self.cost)

        llm.call_claude_with_retry = _stub
        return self

    def __exit__(self, *exc):
        llm.call_claude_with_retry = self._original


def _good_json(dish="豚肉と春キャベツの梅じょうゆ炒め", genre="和") -> str:
    return json.dumps({
        "dish_name": dish,
        "ingredients_summary": "豚こま切れ、春キャベツ、梅干し、しょうゆ",
        "genre": genre,
        "column_title": "梅とキャベツの春炒め",
        "column_body": "春キャベツの甘みと梅の酸味が出会う。" + "あ" * 200,
    }, ensure_ascii=False)


# ---------------------------------------------------------------------------
# (a) get_season boundary tests
# ---------------------------------------------------------------------------

def test_get_season_march():
    _check("a1 3月 → 春", cooking_generator.get_season(3) == "春")


def test_get_season_june():
    _check("a2 6月 → 夏", cooking_generator.get_season(6) == "夏")


def test_get_season_september():
    _check("a3 9月 → 秋", cooking_generator.get_season(9) == "秋")


def test_get_season_december():
    _check("a4 12月 → 冬", cooking_generator.get_season(12) == "冬")


def test_get_season_january():
    _check("a5 1月 → 冬", cooking_generator.get_season(1) == "冬")


def test_get_season_may():
    _check("a6 5月 → 春", cooking_generator.get_season(5) == "春")


# ---------------------------------------------------------------------------
# (b) Happy path
# ---------------------------------------------------------------------------

def test_generate_cooking_happy_path():
    today = date(2026, 5, 3)
    history = {"history": []}
    with _StubLLM(text=_good_json(), cost=0.06) as stub:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "cooking_history.json"
            result = cooking_generator.generate_cooking_column(
                target_date=today, history=history, persist=True,
                history_path=path,
            )
            saved = json.loads(path.read_text(encoding="utf-8"))
    ok = (
        result["dish_name"] == "豚肉と春キャベツの梅じょうゆ炒め"
        and result["genre"] == "和"
        and result["is_fallback"] is False
        and result["cost_usd"] == 0.06
        and len(saved["history"]) == 1
        and saved["history"][0]["dish_name"] == "豚肉と春キャベツの梅じょうゆ炒め"
        and saved["history"][0]["date"] == "2026-05-03"
    )
    _check("b1 happy path: parsed + history persisted to disk", ok,
           f"is_fallback={result['is_fallback']}, history_len={len(saved['history'])}")


def test_user_message_includes_season_and_history():
    today = date(2026, 5, 3)  # 5月 = 春
    history = {"history": [
        {"dish_name": "親子丼", "genre": "和", "date": "2026-05-02"},
        {"dish_name": "麻婆豆腐風", "genre": "中", "date": "2026-05-01"},
    ]}
    with _StubLLM(text=_good_json()) as stub:
        cooking_generator.generate_cooking_column(
            target_date=today, history=history, persist=False,
        )
    user = stub.calls[0].get("user", "")
    ok = (
        "5月" in user
        and "春" in user
        and "親子丼" in user
        and "麻婆豆腐風" in user
        and ("和" in user or "中" in user)
    )
    _check("b2 user message: month + season + history + recent_genres", ok,
           f"user[:80]={user[:80]!r}")


def test_user_message_empty_history():
    today = date(2026, 5, 3)
    history = {"history": []}
    with _StubLLM(text=_good_json()) as stub:
        cooking_generator.generate_cooking_column(
            target_date=today, history=history, persist=False,
        )
    user = stub.calls[0].get("user", "")
    ok = "履歴なし" in user or "なし" in user
    _check("b3 empty history → 'なし' marker in user msg", ok)


# ---------------------------------------------------------------------------
# (c) Genre diversity logic — recent_genres()
# ---------------------------------------------------------------------------

def test_recent_genres_lookback():
    today = date(2026, 5, 5)
    history = {"history": [
        {"dish_name": "1", "genre": "和", "date": "2026-04-30"},  # too old
        {"dish_name": "2", "genre": "洋", "date": "2026-05-02"},   # 3 days ago
        {"dish_name": "3", "genre": "中", "date": "2026-05-03"},   # 2 days ago
        {"dish_name": "4", "genre": "和", "date": "2026-05-04"},   # 1 day ago
    ]}
    recent = cooking_generator.recent_genres(history, today, days=3)
    # newest first
    ok = recent == ["和", "中", "洋"]
    _check("c1 recent_genres last 3 days, newest first", ok, f"got {recent}")


def test_recent_dish_names_30_day_window():
    today = date(2026, 5, 5)
    history = {"history": [
        {"dish_name": "old", "genre": "和", "date": "2026-04-04"},  # 31 days ago — too old
        {"dish_name": "in_window_a", "genre": "和", "date": "2026-04-10"},  # 25 days
        {"dish_name": "in_window_b", "genre": "洋", "date": "2026-05-04"},
    ]}
    names = cooking_generator.recent_dish_names(history, today, days=30)
    ok = "in_window_a" in names and "in_window_b" in names and "old" not in names
    _check("c2 recent_dish_names: 30-day cutoff", ok, f"names={names}")


# ---------------------------------------------------------------------------
# (d) Fallback paths
# ---------------------------------------------------------------------------

def test_llm_exception_fallback():
    today = date(2026, 5, 3)
    history = {"history": []}
    with _StubLLM(raise_exc=RuntimeError("API timeout")):
        result = cooking_generator.generate_cooking_column(
            target_date=today, history=history, persist=False,
        )
    ok = (
        result["is_fallback"] is True
        and result["dish_name"] == "鮭の塩焼き定食"
        and result["genre"] == "和"
        and result["cost_usd"] == 0.0
    )
    _check("d1 LLM exception → static fallback (鮭の塩焼き定食)", ok,
           f"dish={result['dish_name']}, is_fallback={result['is_fallback']}")


def test_non_json_response_fallback():
    today = date(2026, 5, 3)
    history = {"history": []}
    with _StubLLM(text="ぜんぜんJSONじゃない応答です", cost=0.02):
        result = cooking_generator.generate_cooking_column(
            target_date=today, history=history, persist=False,
        )
    ok = (
        result["is_fallback"] is True
        and result["dish_name"] == "鮭の塩焼き定食"
        and result["cost_usd"] == 0.02  # cost still incurred
    )
    _check("d2 non-JSON response → static fallback (cost recorded)", ok,
           f"is_fallback={result['is_fallback']}, cost={result['cost_usd']}")


def test_invalid_genre_fallback():
    today = date(2026, 5, 3)
    history = {"history": []}
    bad = json.dumps({
        "dish_name": "謎料理",
        "ingredients_summary": "材料",
        "genre": "アフリカン",  # invalid
        "column_title": "title",
        "column_body": "body" * 100,
    }, ensure_ascii=False)
    with _StubLLM(text=bad):
        result = cooking_generator.generate_cooking_column(
            target_date=today, history=history, persist=False,
        )
    _check("d3 invalid genre → static fallback", result["is_fallback"] is True)


# ---------------------------------------------------------------------------
# (e) System prompt content
# ---------------------------------------------------------------------------

def test_system_prompt_contains_cooking_guidance():
    today = date(2026, 5, 3)
    history = {"history": []}
    with _StubLLM(text=_good_json()) as stub:
        cooking_generator.generate_cooking_column(
            target_date=today, history=history, persist=False,
        )
    sys_arg = stub.calls[0].get("system", "")
    ok = "Tribune厨房" in sys_arg and "辛くない" in sys_arg and "30分以内" in sys_arg
    _check("e1 system prompt: Tribune厨房 + 辛くない + 30分以内", ok)


# ---------------------------------------------------------------------------
# Test runner
# ---------------------------------------------------------------------------

def main() -> int:
    print("Page 5 — cooking_generator tests")
    print()
    print("(a) get_season boundary:")
    test_get_season_march()
    test_get_season_june()
    test_get_season_september()
    test_get_season_december()
    test_get_season_january()
    test_get_season_may()
    print()
    print("(b) Happy path + prompt building:")
    test_generate_cooking_happy_path()
    test_user_message_includes_season_and_history()
    test_user_message_empty_history()
    print()
    print("(c) Genre diversity / dish name window:")
    test_recent_genres_lookback()
    test_recent_dish_names_30_day_window()
    print()
    print("(d) Fallback paths:")
    test_llm_exception_fallback()
    test_non_json_response_fallback()
    test_invalid_genre_fallback()
    print()
    print("(e) System prompt content:")
    test_system_prompt_contains_cooking_guidance()
    print()
    print(f"=== {PASS} passed, {FAIL} failed ===")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
