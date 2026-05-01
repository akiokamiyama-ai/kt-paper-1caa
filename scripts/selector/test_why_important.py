"""Unit tests for scripts/selector/why_important.py.

Run::

    python3 -m scripts.selector.test_why_important

Covers:
* (a) static_why_important — output structure (3 keys, all strings, non-empty)
* (b) _validate_response — JSON 構造 / 必須キー / 追加キー / 文字数
* (c) Warning detection — 疑問形 / 命令形 / 3社固有名詞
* (d) generate_why_important happy path (LLM stubbed)
* (e) Fallback paths — non-JSON / missing keys / extreme length / dict→ValidationError
"""

from __future__ import annotations

import sys

from ..lib import llm
from . import why_important

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


def _make_response(text: str) -> llm.ClaudeResponse:
    return llm.ClaudeResponse(
        text=text,
        model="stub",
        input_tokens=100,
        output_tokens=50,
        cache_creation_tokens=0,
        cache_read_tokens=0,
        cost_usd=0.001,
        stop_reason="end_turn",
        raw_id="stub",
    )


class _StubLLM:
    """Replace llm.call_claude_with_retry. Supports a list of responses
    (consumed in order) so retry behavior can be tested."""

    def __init__(self, *, text):
        self.text = text  # str | list[str]
        self.calls: list[dict] = []
        self._original = None

    def __enter__(self):
        self._original = llm.call_claude_with_retry

        def _stub(**kwargs):
            self.calls.append(kwargs)
            t = self.text
            if isinstance(t, list):
                idx = min(len(self.calls) - 1, len(t) - 1)
                return _make_response(t[idx])
            return _make_response(t)

        llm.call_claude_with_retry = _stub
        return self

    def __exit__(self, *exc):
        llm.call_claude_with_retry = self._original


# ---------------------------------------------------------------------------
# Sample articles
# ---------------------------------------------------------------------------

def _sample_article() -> dict:
    return {
        "url": "https://example.test/top",
        "title": "Sample top article",
        "title_ja": "サンプルのトップ記事",
        "description": "This is the article description.",
        "desc_ja": "これは記事の description（日本語訳）です。",
        "body": "",
        "source_name": "The Economist",
        "美意識1": 7, "美意識3": 6, "美意識5": 5, "美意識6": 4, "美意識8": 3,
        "美意識2_machine": 0,  # mainstream=true
        "evaluation_reason": {
            "1": "構造×細部 reason",
            "3": "領域横断 reason",
            "5": "他者性 reason",
            "6": "マイノリティ reason",
            "8": "行動経済学 reason",
        },
        "pub_date": "2026-04-30T10:00:00+00:00",
    }


def _valid_points_json() -> str:
    p1 = "Foresight が、米中の半導体規制競争が決定的局面に入り、日本が産業政策の選択を迫られていると報じた。"
    p2 = "経済安全保障とテクノ覇権の交差点で、日本企業の調達戦略・サプライチェーン設計が中期的に変わる可能性が高い。"
    p3 = "地経学的にどの線で踏みとどまるかは目利きの判断。複数領域を架橋して読み、6〜18ヶ月の調達リードタイムで何が動くかを観察したい。"
    return (
        '{"point_1_subject": "' + p1 + '", '
        '"point_2_significance": "' + p2 + '", '
        '"point_3_executive_perspective": "' + p3 + '"}'
    )


# ---------------------------------------------------------------------------
# (a) static_why_important
# ---------------------------------------------------------------------------

def test_static_returns_3keys():
    out = why_important.static_why_important(_sample_article())
    ok = (
        isinstance(out, dict)
        and set(out.keys()) == set(why_important.REQUIRED_KEYS)
        and all(isinstance(v, str) and v.strip() for v in out.values())
    )
    _check("a1 static_why_important returns 3-key dict of non-empty strings", ok,
           f"keys={sorted(out.keys())}")


def test_static_embeds_title_in_p1():
    art = _sample_article()
    out = why_important.static_why_important(art)
    ok = "サンプルのトップ記事" in out["point_1_subject"]
    _check("a2 static fallback embeds title_ja in point_1_subject", ok)


def test_static_no_extra_keys():
    out = why_important.static_why_important(_sample_article())
    extras = set(out.keys()) - set(why_important.REQUIRED_KEYS)
    _check("a3 static returns no extra keys", not extras, f"extras={extras}")


# ---------------------------------------------------------------------------
# (b) _validate_response — structure
# ---------------------------------------------------------------------------

def test_validate_clean_response():
    p = "あ" * 80
    response = {
        "point_1_subject": p,
        "point_2_significance": p,
        "point_3_executive_perspective": p,
    }
    cleaned, warnings = why_important._validate_response(response)
    ok = cleaned == response and warnings == []
    _check("b1 valid 3-key response → no warnings", ok,
           f"warnings={warnings}")


def test_validate_missing_key_raises():
    raised = False
    try:
        why_important._validate_response({
            "point_1_subject": "あ" * 80,
            "point_2_significance": "あ" * 80,
            # point_3 missing
        })
    except why_important.ValidationError:
        raised = True
    _check("b2 missing required key raises ValidationError", raised)


def test_validate_extra_key_raises():
    raised = False
    try:
        why_important._validate_response({
            "point_1_subject": "あ" * 80,
            "point_2_significance": "あ" * 80,
            "point_3_executive_perspective": "あ" * 80,
            "extra_field": "should not be here",
        })
    except why_important.ValidationError:
        raised = True
    _check("b3 extra key raises ValidationError", raised)


def test_validate_extreme_length_raises():
    raised = False
    try:
        why_important._validate_response({
            "point_1_subject": "あ" * 250,  # > 200
            "point_2_significance": "あ" * 80,
            "point_3_executive_perspective": "あ" * 80,
        })
    except why_important.ValidationError:
        raised = True
    _check("b4 length > 200 raises ValidationError", raised)


def test_validate_too_short_raises():
    raised = False
    try:
        why_important._validate_response({
            "point_1_subject": "あ" * 20,  # < 30
            "point_2_significance": "あ" * 80,
            "point_3_executive_perspective": "あ" * 80,
        })
    except why_important.ValidationError:
        raised = True
    _check("b5 length < 30 raises ValidationError", raised)


def test_validate_non_dict_raises():
    raised = False
    try:
        why_important._validate_response(["not", "a", "dict"])
    except why_important.ValidationError:
        raised = True
    _check("b6 non-dict raises ValidationError", raised)


def test_validate_soft_band_warns():
    response = {
        "point_1_subject": "あ" * 130,  # > 120 soft, < 200 hard
        "point_2_significance": "あ" * 80,
        "point_3_executive_perspective": "あ" * 80,
    }
    cleaned, warnings = why_important._validate_response(response)
    ok = (
        cleaned["point_1_subject"] == "あ" * 130
        and any("length 130" in w for w in warnings)
    )
    _check("b7 length 130 (in retry band but soft-out) → adopted with warning",
           ok, f"warnings={warnings}")


# ---------------------------------------------------------------------------
# (c) Warning detection — 疑問形 / 命令形 / 3社固有名詞
# ---------------------------------------------------------------------------

def test_warn_question_mark():
    response = {
        "point_1_subject": "本日の論点は何か？" + ("あ" * 70),
        "point_2_significance": "あ" * 80,
        "point_3_executive_perspective": "あ" * 80,
    }
    response["point_1_subject"] = "あ" * 70 + "本当にそうなのだろうか？"
    cleaned, warnings = why_important._validate_response(response)
    ok = any("question mark" in w for w in warnings)
    _check("c1 trailing ？ triggers warning", ok, f"warnings={warnings}")


def test_warn_imperative():
    response = {
        "point_1_subject": "ここで深く考察すべきである" + ("あ" * 60),
        "point_2_significance": "あ" * 80,
        "point_3_executive_perspective": "あ" * 80,
    }
    cleaned, warnings = why_important._validate_response(response)
    ok = any("imperative" in w for w in warnings)
    _check("c2 「〜すべき」 triggers imperative warning", ok,
           f"warnings={warnings}")


def test_warn_imperative_seyo():
    response = {
        "point_1_subject": "あ" * 60 + "ここで思索せよ、と本紙は読み解く。",
        "point_2_significance": "あ" * 80,
        "point_3_executive_perspective": "あ" * 80,
    }
    cleaned, warnings = why_important._validate_response(response)
    ok = any("imperative" in w for w in warnings)
    _check("c3 「〜せよ」 triggers imperative warning", ok,
           f"warnings={warnings}")


def test_warn_company_cocolomi():
    response = {
        "point_1_subject": "Cocolomi の事業文脈に踏み込んだ言及" + ("あ" * 60),
        "point_2_significance": "あ" * 80,
        "point_3_executive_perspective": "あ" * 80,
    }
    cleaned, warnings = why_important._validate_response(response)
    ok = any("Cocolomi" in w for w in warnings)
    _check("c4 「Cocolomi」 triggers 3社固有名詞 warning", ok,
           f"warnings={warnings}")


def test_warn_company_human_energy():
    response = {
        "point_1_subject": "あ" * 60 + "Human Energy の研修事業に関する話題。",
        "point_2_significance": "あ" * 80,
        "point_3_executive_perspective": "あ" * 80,
    }
    cleaned, warnings = why_important._validate_response(response)
    ok = any("Human Energy" in w for w in warnings)
    _check("c5 「Human Energy」 triggers 3社固有名詞 warning", ok,
           f"warnings={warnings}")


def test_warn_company_web_repo():
    response = {
        "point_1_subject": "あ" * 60 + "Web-Repo のフランチャイズ業界話題。",
        "point_2_significance": "あ" * 80,
        "point_3_executive_perspective": "あ" * 80,
    }
    cleaned, warnings = why_important._validate_response(response)
    ok = any("Web-Repo" in w for w in warnings)
    _check("c6 「Web-Repo」 triggers 3社固有名詞 warning", ok,
           f"warnings={warnings}")


# ---------------------------------------------------------------------------
# (d) generate_why_important — happy path
# ---------------------------------------------------------------------------

def test_generate_happy_path():
    art = _sample_article()
    with _StubLLM(text=_valid_points_json()):
        result = why_important.generate_why_important(art)
    ok = (
        isinstance(result, dict)
        and set(result.keys()) == set(why_important.REQUIRED_KEYS)
        and all(isinstance(v, str) for v in result.values())
    )
    _check("d1 generate_why_important happy path returns clean 3-key dict",
           ok, f"keys={sorted(result.keys())}")


def test_generate_strips_code_fence():
    art = _sample_article()
    fenced = "```json\n" + _valid_points_json() + "\n```"
    with _StubLLM(text=fenced):
        result = why_important.generate_why_important(art)
    ok = "point_1_subject" in result
    _check("d2 generate_why_important strips ```json fences", ok)


# ---------------------------------------------------------------------------
# (e) Fallback paths — caller catches LLMError / ValidationError
# ---------------------------------------------------------------------------

def test_generate_non_json_raises_llm_error():
    """非JSON応答 → 1回リトライ → 失敗 → LLMError."""
    art = _sample_article()
    raised = False
    with _StubLLM(text="これは普通のテキスト応答で JSON ではありません"):
        try:
            why_important.generate_why_important(art)
        except why_important.LLMError:
            raised = True
    _check("e1 non-JSON response → LLMError after retry", raised)


def test_generate_missing_key_raises_validation_error():
    """1回目で必須キー欠落 → ValidationError (parsing は成功)."""
    art = _sample_article()
    bad = '{"point_1_subject": "' + "あ" * 80 + '", "point_2_significance": "' + "あ" * 80 + '"}'
    raised = False
    with _StubLLM(text=bad):
        try:
            why_important.generate_why_important(art)
        except why_important.ValidationError:
            raised = True
    _check("e2 missing point_3 → ValidationError", raised)


def test_generate_retry_then_success():
    """1回目は壊れた応答 → 2回目で正常応答 → success."""
    art = _sample_article()
    responses = ["bad text", _valid_points_json()]
    with _StubLLM(text=responses) as stub:
        result = why_important.generate_why_important(art)
    ok = (
        result.get("point_1_subject")
        and len(stub.calls) == 2
    )
    _check("e3 retry: bad → good → success on 2nd attempt", ok,
           f"calls={len(stub.calls)}")


def test_generate_fallback_chain_in_caller():
    """Caller pattern: try generate, except → static. Verifies fallback dict
    structure remains identical to LLM-generated dict."""
    art = _sample_article()
    with _StubLLM(text="garbage non-json"):
        try:
            points = why_important.generate_why_important(art)
        except (why_important.LLMError, why_important.ValidationError):
            points = why_important.static_why_important(art)
    ok = set(points.keys()) == set(why_important.REQUIRED_KEYS)
    _check("e4 caller fallback chain → static dict has same 3-key shape", ok,
           f"keys={sorted(points.keys())}")


# ---------------------------------------------------------------------------
# Test runner
# ---------------------------------------------------------------------------

def main() -> int:
    print("why_important unit tests")
    print()

    print("(a) static_why_important:")
    test_static_returns_3keys()
    test_static_embeds_title_in_p1()
    test_static_no_extra_keys()

    print()
    print("(b) _validate_response — structure:")
    test_validate_clean_response()
    test_validate_missing_key_raises()
    test_validate_extra_key_raises()
    test_validate_extreme_length_raises()
    test_validate_too_short_raises()
    test_validate_non_dict_raises()
    test_validate_soft_band_warns()

    print()
    print("(c) Warning detection — 疑問形 / 命令形 / 3社固有名詞:")
    test_warn_question_mark()
    test_warn_imperative()
    test_warn_imperative_seyo()
    test_warn_company_cocolomi()
    test_warn_company_human_energy()
    test_warn_company_web_repo()

    print()
    print("(d) generate_why_important — happy path:")
    test_generate_happy_path()
    test_generate_strips_code_fence()

    print()
    print("(e) Fallback paths:")
    test_generate_non_json_raises_llm_error()
    test_generate_missing_key_raises_validation_error()
    test_generate_retry_then_success()
    test_generate_fallback_chain_in_caller()

    print()
    print(f"=== {PASS} passed, {FAIL} failed ===")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
