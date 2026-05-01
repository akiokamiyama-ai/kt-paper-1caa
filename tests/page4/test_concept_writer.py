"""Unit tests for scripts/page4/concept_writer.py.

Run::

    python3 -m tests.page4.test_concept_writer

LLM is monkey-patched via ``llm.call_claude_with_retry`` replacement.
"""

from __future__ import annotations

import sys

from scripts.lib import llm
from scripts.page4 import concept_writer

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
    """Replace llm.call_claude_with_retry; supports static text or exception."""

    def __init__(self, *, text: str | None = None, raise_exc: Exception | None = None,
                 cost: float = 0.05):
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


def _sample_concept() -> dict:
    return {
        "id": "phenomenology",
        "name_ja": "現象学",
        "name_en": "Phenomenology",
        "domain": "現象学",
        "thinkers": ["フッサール", "ハイデガー"],
        "seed": "意識に現れるもの（現象）を、先入観を括弧に入れてそのあるがままに記述しようとする哲学的方法。",
        "related": ["intentionality"],
        "difficulty": 2,
    }


# ---------------------------------------------------------------------------
# (a) Happy path
# ---------------------------------------------------------------------------

def test_write_essay_happy_path():
    essay_text = "現象学とは、私たちの意識に立ち現れる事象そのものを記述することを目指した方法論である。" * 5
    with _StubLLM(text=essay_text, cost=0.045) as stub:
        result = concept_writer.write_essay(_sample_concept())
    ok = (
        result["essay"] == essay_text
        and result["is_fallback"] is False
        and result["concept"]["id"] == "phenomenology"
        and result["cost_usd"] == 0.045
        and len(stub.calls) == 1
    )
    _check("a1 happy path: essay text returned, cost recorded", ok,
           f"is_fallback={result['is_fallback']}, cost={result['cost_usd']}")


def test_write_essay_user_message_includes_seed():
    """User message must include seed so LLM has context."""
    with _StubLLM(text="essay") as stub:
        concept_writer.write_essay(_sample_concept())
    user_msg = stub.calls[0].get("user", "")
    ok = "意識に現れるもの" in user_msg and "フッサール" in user_msg
    _check("a2 user message contains seed + thinkers", ok,
           f"user_msg first 100 chars: {user_msg[:100]!r}")


# ---------------------------------------------------------------------------
# (b) Fallback paths
# ---------------------------------------------------------------------------

def test_write_essay_empty_response_fallback():
    """Empty LLM response → fallback to seed."""
    with _StubLLM(text="", cost=0.001) as stub:
        result = concept_writer.write_essay(_sample_concept())
    ok = (
        result["is_fallback"] is True
        and "意識に現れるもの" in result["essay"]
        and result["cost_usd"] == 0.001  # cost still recorded
    )
    _check("b1 empty response → fallback to seed (cost recorded)", ok,
           f"is_fallback={result['is_fallback']}, essay first 30: {result['essay'][:30]!r}")


def test_write_essay_llm_exception_fallback():
    """LLM exception → fallback to seed (no cost charged)."""
    with _StubLLM(raise_exc=RuntimeError("API timeout")) as stub:
        result = concept_writer.write_essay(_sample_concept())
    ok = (
        result["is_fallback"] is True
        and "意識に現れるもの" in result["essay"]
        and result["cost_usd"] == 0.0
    )
    _check("b2 LLM exception → fallback to seed", ok,
           f"is_fallback={result['is_fallback']}, cost={result['cost_usd']}")


def test_write_essay_concept_with_no_seed():
    """Concept without seed → fallback to safe placeholder text."""
    concept = _sample_concept()
    concept["seed"] = ""
    with _StubLLM(raise_exc=RuntimeError("network error")):
        result = concept_writer.write_essay(concept)
    ok = result["is_fallback"] is True and result["essay"]  # non-empty
    _check("b3 missing seed + LLM fail → safe placeholder", ok,
           f"essay={result['essay'][:50]!r}")


# ---------------------------------------------------------------------------
# (c) System prompt
# ---------------------------------------------------------------------------

def test_system_prompt_passed():
    with _StubLLM(text="ok") as stub:
        concept_writer.write_essay(_sample_concept())
    sys_arg = stub.calls[0].get("system", "")
    ok = "今週の概念" in sys_arg and "400〜600字" in sys_arg
    _check("c1 system prompt sent: includes spec rules", ok)


# ---------------------------------------------------------------------------
# Test runner
# ---------------------------------------------------------------------------

def main() -> int:
    print("Page 4 — concept_writer tests")
    print()
    print("(a) Happy path:")
    test_write_essay_happy_path()
    test_write_essay_user_message_includes_seed()
    print()
    print("(b) Fallback paths:")
    test_write_essay_empty_response_fallback()
    test_write_essay_llm_exception_fallback()
    test_write_essay_concept_with_no_seed()
    print()
    print("(c) System prompt:")
    test_system_prompt_passed()
    print()
    print(f"=== {PASS} passed, {FAIL} failed ===")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
