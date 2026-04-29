"""Unit tests for Page 2 pipeline (scripts/selector/page2.py).

Run with::

    python3 -m scripts.selector.test_page2

Covers 15 cases across 5 categories:

(a) compute_page2_score — boundary / typical / missing fields              [3]
(b) select_page2_articles — 5-stage fallback (high/medium/reference/cross/none) [5]
(c) extract_company_context — 3 valid keys + invalid                       [3]
(d) Step 1 JSON validation — valid / clamp + missing reason                [2]
(e) Step 2 length — within range / fallback on parse failure               [2]

LLM is monkey-patched via ``llm.call_claude_with_retry`` replacement so
tests do not hit the API.
"""

from __future__ import annotations

import re
import sys
from typing import Any

from ..lib import llm
from . import page2

# ---------------------------------------------------------------------------
# Test infrastructure
# ---------------------------------------------------------------------------

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
    """Context manager that replaces llm.call_claude_with_retry.

    Two modes:
    * Static (``text=...``): always return that text. For Step 1/2 JSON
      validation tests where the response shape is the subject under test.
    * Smart (default, Step 1/Step 2 auto-detect): build a JSON response
      matching the input ids/structure. For fallback selection tests where
      the LLM is incidental and we just need realistic-shaped scores.
    """

    def __init__(
        self,
        *,
        text: str | list[str] | None = None,
        mi: int = 7,
        rs: int = 6,
        question: str = (
            "経産省ガイドラインを踏まえ、Cocolomi として今週中に着手すべき"
            "事例研究2本はどれか？"
        ),
    ):
        self.text = text
        self.mi = mi
        self.rs = rs
        self.question = question
        self.calls: list[dict] = []
        self._original = None

    def _smart_response(self, user: str) -> str:
        """Build a JSON response that fits whichever step is being asked."""
        ids = re.findall(r"\[(art_\d{3})\]", user)
        if "【既存の評価結果】" in user or len(ids) == 0:
            # Step 2 mode (single article)
            aid = ids[0] if ids else "art_001"
            return f'{{"article_id": "{aid}", "morning_question": "{self.question}"}}'
        # Step 1 mode (N articles)
        evals = []
        for aid in ids:
            evals.append(
                f'{{"article_id": "{aid}", '
                f'"scores": {{"managerial_implication": {self.mi}, '
                f'"regulatory_signal": {self.rs}}}, '
                f'"reasons": {{"managerial_implication": "stub-reason-mi", '
                f'"regulatory_signal": "stub-reason-rs"}}}}'
            )
        return '{"evaluations": [' + ",".join(evals) + "]}"

    def __enter__(self):
        self._original = llm.call_claude_with_retry

        def _stub(**kwargs):
            self.calls.append(kwargs)
            if self.text is not None:
                if isinstance(self.text, list):
                    idx = min(len(self.calls) - 1, len(self.text) - 1)
                    return _make_response(self.text[idx])
                return _make_response(self.text)
            return _make_response(self._smart_response(kwargs.get("user", "")))

        llm.call_claude_with_retry = _stub
        return self

    def __exit__(self, *exc):
        llm.call_claude_with_retry = self._original


# ---------------------------------------------------------------------------
# (a) compute_page2_score — 3 cases
# ---------------------------------------------------------------------------

def test_score_boundary_max():
    art = {"final_score": 100.0, "managerial_implication": 10, "regulatory_signal": 10}
    s = page2.compute_page2_score(art)
    _check("a1 boundary max (all 100/10/10)", s == 100.0, f"got {s}")


def test_score_typical():
    # 美意識60 × 0.30 + 含意8 × 10 × 0.40 + 規制5 × 10 × 0.30
    # = 18 + 32 + 15 = 65.0
    art = {"final_score": 60.0, "managerial_implication": 8, "regulatory_signal": 5}
    s = page2.compute_page2_score(art)
    _check("a2 typical (60/8/5 → 65.0)", abs(s - 65.0) < 0.01, f"got {s}")


def test_score_missing_fields():
    # 美意識のみ 80、Step 1 評価未実施 → 80*0.30 = 24.0
    art = {"final_score": 80.0}
    s = page2.compute_page2_score(art)
    _check("a3 missing step1 fields (80/?/? → 24.0)", abs(s - 24.0) < 0.01, f"got {s}")


# ---------------------------------------------------------------------------
# (b) select_page2_articles — 5-stage fallback (5 cases)
# ---------------------------------------------------------------------------

def _make_scored(category: str, page2_score: float | None = None,
                 final_score: float = 50.0, mi: int = 5, rs: int = 5,
                 url_suffix: str = "art1") -> dict:
    """Build a scored article dict in the shape that select_page2_articles expects."""
    return {
        "url": f"https://example.test/{category.replace(':', '_')}/{url_suffix}",
        "title": f"Test article in {category}",
        "description": "A test description that is long enough to not trigger Mode B path of Stage 2." * 2,
        "body": "",
        "source_name": f"test-source-{category.replace(':', '_')}",
        "category": category,
        "final_score": final_score,
        "managerial_implication": mi,
        "regulatory_signal": rs,
        "managerial_implication_reason": "stub",
        "regulatory_signal_reason": "stub",
        "page2_final_score": page2_score
        if page2_score is not None
        else page2.compute_page2_score(
            {"final_score": final_score, "managerial_implication": mi, "regulatory_signal": rs}
        ),
        "美意識1": 5, "美意識3": 5, "美意識5": 5, "美意識6": 5, "美意識8": 5,
    }


def test_select_stage_high():
    cocolomi = _make_scored("companies:Cocolomi", final_score=80, mi=8, rs=6)
    he = _make_scored("companies:Human Energy", final_score=80, mi=8, rs=6)
    wr = _make_scored("companies:Web-Repo", final_score=80, mi=8, rs=6)
    selections, errors, cost = page2.select_page2_articles(
        [cocolomi, he, wr], fetcher_fn=None, threshold=40.0,
    )
    ok = (
        selections["cocolomi"].stage_used == "high"
        and selections["human_energy"].stage_used == "high"
        and selections["web_repo"].stage_used == "high"
    )
    _check("b1 stage='high' for all 3 companies above threshold", ok)


def test_select_stage_medium():
    """High に該当なし、Medium で fetcher_fn が候補を返す。Step 1 LLM call は smart stub が応答。"""
    def fetcher(*, name_substring=None, category=None, priority=None, limit=8):
        if priority == "medium":
            return [_make_scored(category or "companies:Cocolomi",
                                  final_score=80, mi=8, rs=6, url_suffix="med1")]
        return []

    cocolomi_low = _make_scored("companies:Cocolomi", final_score=5, mi=0, rs=0)  # below 40
    he = _make_scored("companies:Human Energy", final_score=80, mi=8, rs=6)
    wr = _make_scored("companies:Web-Repo", final_score=80, mi=8, rs=6)
    with _StubLLM():
        selections, errors, cost = page2.select_page2_articles(
            [cocolomi_low, he, wr], fetcher_fn=fetcher, threshold=40.0,
        )
    ok = (
        selections["cocolomi"].stage_used == "medium"
        and selections["cocolomi"].article is not None
        and "med1" in selections["cocolomi"].article.get("url", "")
    )
    _check("b2 stage='medium' when high empty + fetcher returns medium", ok,
           f"got stage={selections['cocolomi'].stage_used}")


def test_select_stage_reference():
    """High/Medium に該当なし、Reference で fetcher_fn が候補を返す。"""
    def fetcher(*, name_substring=None, category=None, priority=None, limit=8):
        if priority == "reference":
            return [_make_scored(category or "companies:Cocolomi",
                                  final_score=70, mi=7, rs=5, url_suffix="ref1")]
        return []  # medium 空

    cocolomi_low = _make_scored("companies:Cocolomi", final_score=5, mi=0, rs=0)
    he = _make_scored("companies:Human Energy", final_score=80, mi=8, rs=6)
    wr = _make_scored("companies:Web-Repo", final_score=80, mi=8, rs=6)
    with _StubLLM():
        selections, _errors, _cost = page2.select_page2_articles(
            [cocolomi_low, he, wr], fetcher_fn=fetcher, threshold=40.0,
        )
    ok = selections["cocolomi"].stage_used == "reference"
    _check("b3 stage='reference' when high+medium empty", ok,
           f"got stage={selections['cocolomi'].stage_used}")


def test_select_stage_cross_industry():
    """High/Medium/Reference 全滅、cross-industry (business+geopolitics) から拾う。

    pre-filter キーワード（Cocolomi 用）を含む記事1本だけ返すように fetcher を構成。
    """
    def fetcher(*, name_substring=None, category=None, priority=None, limit=8):
        if category in ("business", "geopolitics"):
            # title に "OpenAI" を含む = Cocolomi pre-filter キーワードのいずれかを含む
            art = _make_scored(category, final_score=60, mi=6, rs=5, url_suffix="cross1")
            art["title"] = "OpenAI announces new partnership for enterprise AI deployment"
            return [art]
        return []

    cocolomi_low = _make_scored("companies:Cocolomi", final_score=5, mi=0, rs=0)
    he = _make_scored("companies:Human Energy", final_score=80, mi=8, rs=6)
    wr = _make_scored("companies:Web-Repo", final_score=80, mi=8, rs=6)
    with _StubLLM():
        selections, _errors, _cost = page2.select_page2_articles(
            [cocolomi_low, he, wr], fetcher_fn=fetcher, threshold=40.0,
        )
    ok = selections["cocolomi"].stage_used == "cross_industry"
    _check("b4 stage='cross_industry' from business/geopolitics", ok,
           f"got stage={selections['cocolomi'].stage_used}")


def test_cross_industry_filter_web_repo():
    """cross-industry pre-filter: web_repo は FC キーワードを含む記事だけ通す。"""
    arts = [
        {"title": "フランチャイズ業界の最新動向", "description": "...", "url": "u1"},
        {"title": "AI技術の進化", "description": "ChatGPT 等の生成AI", "url": "u2"},
        {"title": "JFA 定時総会開催", "description": "...", "url": "u3"},
        {"title": "今週の経済", "description": "為替・株価について", "url": "u4"},
        {"title": "本部経営戦略", "description": "メガフランチャイジーの動向", "url": "u5"},
    ]
    filtered = page2._cross_industry_filter(arts, "web_repo")
    urls = {a["url"] for a in filtered}
    expected = {"u1", "u3", "u5"}  # フランチャイズ / JFA / 本部 を含むもの
    ok = urls == expected
    _check(
        "b6 _cross_industry_filter(web_repo) keeps only FC-keyword articles",
        ok,
        f"got urls={sorted(urls)}, expected={sorted(expected)}",
    )


def test_select_stage_none():
    """全段階で候補なし → stage='none'。"""
    def empty_fetcher(*, name_substring=None, category=None, priority=None, limit=8):
        return []

    cocolomi_low = _make_scored("companies:Cocolomi", final_score=5, mi=0, rs=0)
    he = _make_scored("companies:Human Energy", final_score=80, mi=8, rs=6)
    wr = _make_scored("companies:Web-Repo", final_score=80, mi=8, rs=6)
    selections, _errors, _cost = page2.select_page2_articles(
        [cocolomi_low, he, wr], fetcher_fn=empty_fetcher, threshold=40.0,
    )
    ok = (
        selections["cocolomi"].stage_used == "none"
        and selections["cocolomi"].article is None
    )
    _check("b5 stage='none' when all stages empty", ok,
           f"got stage={selections['cocolomi'].stage_used}")


# ---------------------------------------------------------------------------
# (c) extract_company_context — 3 cases
# ---------------------------------------------------------------------------

_DUMMY_CONTEXT_TEXT = """# header

## 1. Cocolomi（生成AI導入支援）

### 事業の本質
日本企業の生成AI導入支援。

### ウォッチ軸
- 規制
- 事例

---

## 2. Human Energy（企業向け研修）

### 事業の本質
研修サービス事業。

---

## 3. Web-Repo（フランチャイズ業界）

### 事業の本質
FCメディア。

---

## 4. プロンプト注入時の使い方
仕様。
"""


def test_context_cocolomi():
    ctx = page2.extract_company_context("cocolomi", doc_text=_DUMMY_CONTEXT_TEXT)
    ok = (
        ctx.startswith("## 事業文脈")
        and "日本企業の生成AI導入支援" in ctx
        and "## 2." not in ctx
        and "## 4." not in ctx
        and "Human Energy" not in ctx
    )
    _check("c1 cocolomi: rename + slice + no leak to other companies", ok)


def test_context_human_energy():
    ctx = page2.extract_company_context("human_energy", doc_text=_DUMMY_CONTEXT_TEXT)
    ok = (
        ctx.startswith("## 事業文脈")
        and "研修サービス事業" in ctx
        and "## 1." not in ctx
        and "## 3." not in ctx
    )
    _check("c2 human_energy: rename + clean slice", ok)


def test_context_invalid_key():
    raised = False
    try:
        page2.extract_company_context("nonexistent_key", doc_text=_DUMMY_CONTEXT_TEXT)
    except KeyError:
        raised = True
    _check("c3 invalid company_key raises KeyError", raised)


# ---------------------------------------------------------------------------
# (d) Step 1 JSON validation — 2 cases
# ---------------------------------------------------------------------------

def test_step1_valid_response():
    """LLM が完璧な JSON を返した場合。"""
    valid_json = """{
  "evaluations": [
    {
      "article_id": "art_001",
      "scores": {"managerial_implication": 7, "regulatory_signal": 8},
      "reasons": {
        "managerial_implication": "事業文脈と直結する具体材料",
        "regulatory_signal": "ガイドライン公布レベル"
      }
    }
  ]
}"""
    art = {
        "url": "https://x.test/1", "title": "T1", "source_name": "S",
        "description": "long enough description for Mode A operation here." * 2,
        "body": "",
    }
    with _StubLLM(text=valid_json):
        evals, errors, cost = page2.evaluate_management_relevance(
            [art], "cocolomi",
        )
    ok = (
        len(evals) == 1
        and evals[0].managerial_implication == 7
        and evals[0].regulatory_signal == 8
        and len(errors) == 0
    )
    _check("d1 step1: valid JSON parses cleanly", ok,
           f"errors={len(errors)}, mi={evals[0].managerial_implication if evals else '-'}")


def test_step1_clamp_and_missing_reason():
    """スコア範囲外＋reason 欠落 → クランプ＋エラーログ。"""
    bad_json = """{
  "evaluations": [
    {
      "article_id": "art_001",
      "scores": {"managerial_implication": 15, "regulatory_signal": -2},
      "reasons": {}
    }
  ]
}"""
    art = {
        "url": "https://x.test/2", "title": "T2", "source_name": "S",
        "description": "long enough description for Mode A operation here." * 2,
        "body": "",
    }
    with _StubLLM(text=bad_json):
        evals, errors, cost = page2.evaluate_management_relevance(
            [art], "cocolomi",
        )
    ok = (
        len(evals) == 1
        and evals[0].managerial_implication == 10  # clamped from 15
        and evals[0].regulatory_signal == 0         # clamped from -2
        and len(errors) >= 4   # 2 clamps + 2 missing reasons
    )
    _check("d2 step1: out-of-range + missing reason → clamp + errors", ok,
           f"got mi={evals[0].managerial_implication}, rs={evals[0].regulatory_signal}, "
           f"errors={len(errors)}")


# ---------------------------------------------------------------------------
# (e) Step 2 length — 2 cases
# ---------------------------------------------------------------------------

def test_step2_within_range():
    """40〜80字の問いを返す典型ケース。"""
    valid_q = "経産省の参照アーキテクチャ公布を踏まえ、Cocolomi として今週中に着手すべき製造業の事例研究2本はどれか？"
    response = '{"article_id": "art_001", "morning_question": "' + valid_q + '"}'
    art = {"url": "https://x.test/3", "title": "T3", "source_name": "S",
           "description": "desc", "body": ""}
    with _StubLLM(text=response):
        question, errors, cost = page2.generate_morning_question(art, "cocolomi")
    qlen = len(question)
    ok = question == valid_q and 40 <= qlen <= 100 and len(errors) == 0
    _check(f"e1 step2: {qlen}-char question within range, no errors", ok)


def test_step2_parse_failure_fallback():
    """JSON でない応答 → 1回リトライ → 失敗時 FALLBACK_QUESTION."""
    bad_response = "ここはJSONではない普通のテキスト応答です"
    art = {"url": "https://x.test/4", "title": "T4", "source_name": "S",
           "description": "desc", "body": ""}
    with _StubLLM(text=bad_response):
        question, errors, cost = page2.generate_morning_question(art, "cocolomi")
    ok = question == page2.FALLBACK_QUESTION and len(errors) >= 1
    _check("e2 step2: non-JSON response → fallback question", ok,
           f"got question={question!r}, errors={len(errors)}")


# ---------------------------------------------------------------------------
# Test runner
# ---------------------------------------------------------------------------

def main() -> int:
    print("Page 2 unit tests")
    print()

    print("(a) compute_page2_score:")
    test_score_boundary_max()
    test_score_typical()
    test_score_missing_fields()

    print()
    print("(b) select_page2_articles — 5-stage fallback + cross-industry pre-filter:")
    test_select_stage_high()
    test_select_stage_medium()
    test_select_stage_reference()
    test_select_stage_cross_industry()
    test_select_stage_none()
    test_cross_industry_filter_web_repo()

    print()
    print("(c) extract_company_context:")
    test_context_cocolomi()
    test_context_human_energy()
    test_context_invalid_key()

    print()
    print("(d) Step 1 JSON validation:")
    test_step1_valid_response()
    test_step1_clamp_and_missing_reason()

    print()
    print("(e) Step 2 length / fallback:")
    test_step2_within_range()
    test_step2_parse_failure_fallback()

    print()
    print(f"=== {PASS} passed, {FAIL} failed ===")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
