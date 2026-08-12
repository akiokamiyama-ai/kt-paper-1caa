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
    ok = "今日の概念" in sys_arg and "400〜600字" in sys_arg
    _check("c1 system prompt sent: includes spec rules", ok)


# ---------------------------------------------------------------------------
# (d) C55 (2026-06-02): マークダウン禁止指示が prompt に含まれる
#
# 6/2 朝刊 4 面 concept で `**サーバントリーダーシップ／Servant Leadership**`
# のような ** がそのまま紙面表示された事象への対策。C52 (1 面論考) と同じ
# 二段ガード — 1 段目は prompt、2 段目は renderer safety net。
# ---------------------------------------------------------------------------

def test_d1_prompt_forbids_markdown_bold():
    """SYSTEM_PROMPT に 'マークダウン' 関連の禁止指示が含まれる."""
    sp = concept_writer.SYSTEM_PROMPT
    ok = "マークダウン" in sp and "**" in sp
    _check(
        "d1 prompt に 'マークダウン' と '**' が登場（禁止指示）",
        ok,
        f"got SYSTEM_PROMPT 末尾: ...{sp[-200:]!r}",
    )


def test_d2_prompt_forbids_emphasis_marks():
    """強調記号の禁止が明示されている."""
    sp = concept_writer.SYSTEM_PROMPT
    _check(
        "d2 prompt に '使用しない' or '禁止' (or 同等の絶対指示) が含まれる",
        "使用しない" in sp or "禁止" in sp,
    )


# ---------------------------------------------------------------------------
# Test runner
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# (e) C158 (Sprint 13, 2026-08-12): 関連概念セクション
#
# 本文と関連概念の解説を **1 回の LLM 呼び出し**で生成し、応答を区切りで割る。
# コスト抑制のため別呼び出しにしない設計なので、「1 回しか呼ばない」ことと
# 「パース失敗時に紙面が落ちない」ことを固定する。
# ---------------------------------------------------------------------------

_REL = [
    {"id": "homeostasis", "name_ja": "ホメオスタシス", "name_en": "Homeostasis",
     "domain": "生理学", "seed": "生体が内部環境を一定に保つ働き。二文目。"},
    {"id": "autopoiesis", "name_ja": "オートポイエーシス", "name_en": "Autopoiesis",
     "domain": "システム論", "seed": "自己を産出し続けるシステム。二文目。"},
]


def _resp_with_related() -> str:
    return (
        f"{concept_writer.ESSAY_MARKER}\n"
        "内的環境という概念は、ベルナールが生理学に導入したものである。" * 4 + "\n"
        f"{concept_writer.RELATED_MARKER}\n"
        "ホメオスタシス: キャノンが生理学的に定式化した後継概念。\n"
        "オートポイエーシス: 内的環境の維持を自己産出として捉え直した系譜。\n"
    )


def test_e1_single_llm_call_for_essay_and_related():
    with _StubLLM(text=_resp_with_related()) as stub:
        out = concept_writer.write_essay(_sample_concept(), _REL)
    _check("e1 LLM 呼び出しは 1 回のみ（コスト抑制の要件）",
           len(stub.calls) == 1, f"got {len(stub.calls)}")
    _check("e2 related 2 件が返る", len(out["related"]) == 2,
           f"got {len(out['related'])}")


def test_e3_related_notes_parsed():
    with _StubLLM(text=_resp_with_related()):
        out = concept_writer.write_essay(_sample_concept(), _REL)
    by = {r["name_ja"]: r for r in out["related"]}
    _check("e3 ホメオスタシスの解説がパースされる",
           "キャノン" in by["ホメオスタシス"]["note"], f"got {by['ホメオスタシス']['note']}")
    _check("e4 is_fallback=False（LLM 由来）",
           by["ホメオスタシス"]["is_fallback"] is False)


def test_e5_markers_stripped_from_body():
    with _StubLLM(text=_resp_with_related()):
        out = concept_writer.write_essay(_sample_concept(), _REL)
    body = out["essay"]
    _check("e5 区切り記号が本文に漏れない（紙面事故の防止）",
           concept_writer.ESSAY_MARKER not in body
           and concept_writer.RELATED_MARKER not in body, f"got {body[:60]}")
    _check("e6 関連概念の解説が本文に混ざらない",
           "キャノン" not in body, f"got {body[-80:]}")


def test_e7_unparseable_response_falls_back_to_seed():
    """区切りが無い応答 → 全体を本文、関連概念は seed fallback（紙面は落とさない）."""
    with _StubLLM(text="区切りの無い普通の本文だけの応答。" * 10):
        out = concept_writer.write_essay(_sample_concept(), _REL)
    _check("e7 パース失敗でも related は 2 件返る",
           len(out["related"]) == 2, f"got {len(out['related'])}")
    _check("e8 fallback は seed の 1 文目",
           out["related"][0]["note"].startswith("生体が内部環境")
           and out["related"][0]["is_fallback"] is True,
           f"got {out['related'][0]}")
    _check("e9 本文は失われない", len(out["essay"]) > 20)


def test_e10_llm_failure_keeps_related_fallback():
    with _StubLLM(raise_exc=RuntimeError("API down")):
        out = concept_writer.write_essay(_sample_concept(), _REL)
    _check("e10 LLM 例外時も related は seed fallback で返る",
           len(out["related"]) == 2 and all(r["is_fallback"] for r in out["related"]),
           f"got {out['related']}")


def test_e11_no_related_argument_is_backward_compatible():
    with _StubLLM(text="本文のみ。" * 20) as stub:
        out = concept_writer.write_essay(_sample_concept())
    _check("e11 related 未指定なら空リスト（旧呼び出しと互換）",
           out["related"] == [], f"got {out['related']}")
    _check("e12 related 未指定なら prompt に区切り指示を入れない",
           concept_writer.RELATED_MARKER not in stub.calls[0]["user"])


def test_e13_prompt_asks_for_connection_not_definition():
    with _StubLLM(text=_resp_with_related()) as stub:
        concept_writer.write_essay(_sample_concept(), _REL)
    user = stub.calls[0]["user"]
    _check("e13 prompt に関連概念名が載る",
           "ホメオスタシス" in user and "オートポイエーシス" in user)
    sysmsg = stub.calls[0]["system"]
    _check("e14 system prompt が『語義説明ではなく繋がり』を要求",
           "繋がる" in sysmsg or "関係" in sysmsg, f"got {sysmsg[-200:]}")


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
    print("(d) C55 (2026-06-02): マークダウン禁止 prompt:")
    test_d1_prompt_forbids_markdown_bold()
    test_d2_prompt_forbids_emphasis_marks()
    print()
    print("(e) C158: 関連概念セクション:")
    test_e1_single_llm_call_for_essay_and_related()
    test_e3_related_notes_parsed()
    test_e5_markers_stripped_from_body()
    test_e7_unparseable_response_falls_back_to_seed()
    test_e10_llm_failure_keeps_related_fallback()
    test_e11_no_related_argument_is_backward_compatible()
    test_e13_prompt_asks_for_connection_not_definition()
    print()
    print(f"=== {PASS} passed, {FAIL} failed ===")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
