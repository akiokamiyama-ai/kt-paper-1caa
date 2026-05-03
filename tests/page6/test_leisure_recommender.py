"""Unit tests for scripts/page6/leisure_recommender.py.

Run::

    python3 -m tests.page6.test_leisure_recommender
"""

from __future__ import annotations

import sys
from datetime import date

from scripts.lib import llm
from scripts.page6 import leisure_recommender, prompts

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
        input_tokens=100, output_tokens=300,
        cache_creation_tokens=0, cache_read_tokens=0,
        cost_usd=cost,
        stop_reason="end_turn", raw_id="stub",
    )


class _StubLLM:
    """Replace llm.call_claude_with_retry; supports static text / list / exception."""

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
            t = self.text
            if isinstance(t, list):
                idx = min(len(self.calls) - 1, len(t) - 1)
                return _make_response(t[idx], cost=self.cost)
            return _make_response(t or "", cost=self.cost)

        llm.call_claude_with_retry = _stub
        return self

    def __exit__(self, *exc):
        llm.call_claude_with_retry = self._original


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------

def _sample_article() -> dict:
    return {
        "url": "https://hayakawa.test/ted-chiang-2026",
        "title": "テッド・チャン新短編集、5月14日に早川書房から",
        "description": "早川書房は、テッド・チャン新短編集の日本語版を5月14日に発売すると発表した。" * 3,
        "source_name": "早川書房",
        "category": "books",
        "pub_date": "2026-04-25T10:00:00+00:00",
        "final_score": 60.0,
        "美意識1": 7,
    }


def _good_column_json() -> str:
    return (
        '{"column_title": "チャンの問いに帰る朝", '
        '"column_body": "テッド・チャンの新短編集が5月14日に早川書房から出る。'
        + 'あ' * 200 + '"}'
    )


# ---------------------------------------------------------------------------
# (a) Happy path — column generation
# ---------------------------------------------------------------------------

def test_generate_column_happy_path_books():
    article = _sample_article()
    with _StubLLM(text=_good_column_json(), cost=0.04):
        column, cost, is_fallback = leisure_recommender._generate_column("books", article)
    ok = (
        column["column_title"] == "チャンの問いに帰る朝"
        and column["column_body"].startswith("テッド・チャンの新短編集")
        and is_fallback is False
        and cost == 0.04
    )
    _check("a1 books happy path: column_title + body parsed, no fallback", ok,
           f"is_fallback={is_fallback}, cost={cost}")


def test_generate_column_strips_code_fence():
    article = _sample_article()
    fenced = "```json\n" + _good_column_json() + "\n```"
    with _StubLLM(text=fenced):
        column, _, is_fallback = leisure_recommender._generate_column("books", article)
    _check("a2 strips ```json fences", is_fallback is False and column["column_title"])


def test_generate_column_eval_guide_in_system():
    """各領域の EVAL_GUIDE が system プロンプトに含まれる."""
    article = _sample_article()
    for area, expected_phrase in (
        ("books", "純文学"),
        ("music", "Radiohead"),
        ("outdoor", "ウルトラライト"),
    ):
        with _StubLLM(text=_good_column_json()) as stub:
            leisure_recommender._generate_column(area, article)
        sys_arg = stub.calls[0].get("system", "")
        ok = expected_phrase in sys_arg and "Tribune" in sys_arg
        _check(
            f"a3 {area}: system prompt contains {expected_phrase!r}",
            ok,
            f"system_first_100={sys_arg[:100]!r}",
        )


# ---------------------------------------------------------------------------
# (b) Fallback paths
# ---------------------------------------------------------------------------

def test_generate_column_llm_exception_fallback():
    article = _sample_article()
    with _StubLLM(raise_exc=RuntimeError("API timeout")):
        column, cost, is_fallback = leisure_recommender._generate_column("books", article)
    ok = (
        is_fallback is True
        and column["column_title"]  # non-empty
        and column["column_body"]
        and cost == 0.0
    )
    _check("b1 LLM exception → description fallback", ok,
           f"is_fallback={is_fallback}, title={column['column_title'][:30]!r}")


def test_generate_column_non_json_fallback():
    article = _sample_article()
    with _StubLLM(text="これは普通のテキストです、JSON ではありません"):
        column, cost, is_fallback = leisure_recommender._generate_column("books", article)
    ok = (
        is_fallback is True
        and column["column_title"]
        and "テッド" in column["column_body"]  # description fallback uses article desc
    )
    _check("b2 non-JSON response → description fallback", ok,
           f"is_fallback={is_fallback}, body[:30]={column['column_body'][:30]!r}")


def test_generate_column_missing_keys_fallback():
    article = _sample_article()
    bad_json = '{"column_title": "あいまいなタイトル"}'  # column_body missing
    with _StubLLM(text=bad_json):
        column, _, is_fallback = leisure_recommender._generate_column("books", article)
    _check("b3 missing column_body key → fallback", is_fallback is True)


# ---------------------------------------------------------------------------
# (c) recommend_for_area orchestration — placeholder when no candidates
# ---------------------------------------------------------------------------

def test_recommend_for_area_unsupported():
    raised = False
    try:
        leisure_recommender.recommend_for_area("invalid_area", target_date=date(2026, 5, 3))
    except ValueError:
        raised = True
    _check("c1 unsupported area raises ValueError", raised)


def test_recommend_for_area_no_candidates_returns_placeholder(monkeypatch_compat=None):
    """fetch_and_score returns empty → placeholder dict."""
    original = leisure_recommender._fetch_and_score_area
    leisure_recommender._fetch_and_score_area = lambda area, **kw: ([], 0.0)
    try:
        result = leisure_recommender.recommend_for_area(
            "books", target_date=date(2026, 5, 3),
        )
    finally:
        leisure_recommender._fetch_and_score_area = original
    ok = (
        result["is_fallback"] is True
        and result["article"] is None
        and result["column_title"] == "本日該当なし"
        and result["fallback_reason"] == "no_candidates_after_stage123"
    )
    _check("c2 zero-candidate: placeholder with fallback_reason", ok,
           f"is_fallback={result['is_fallback']}, reason={result.get('fallback_reason')}")


# ---------------------------------------------------------------------------
# (d) Books area filter — page3-R6 / page4 sources excluded
# ---------------------------------------------------------------------------

def test_books_filter_excludes_quanta():
    """Quanta Magazine = 自然科学ノンフ → page3 R6, must be excluded from page6 books."""
    art = {"source_name": "Quanta Magazine", "title": "x", "description": "y"}
    _check("d1 books area excludes Quanta Magazine",
           leisure_recommender._belongs_to_area(art, "books") is False)


def test_books_filter_excludes_aeon():
    """Aeon = 人文 → page4, must be excluded from page6 books."""
    art = {"source_name": "Aeon", "title": "x", "description": "y"}
    _check("d2 books area excludes Aeon",
           leisure_recommender._belongs_to_area(art, "books") is False)


def test_books_filter_includes_hayakawa():
    art = {"source_name": "早川書房", "title": "x", "description": "y"}
    _check("d3 books area includes 早川書房 (literary fiction)",
           leisure_recommender._belongs_to_area(art, "books") is True)


def test_music_outdoor_no_filter():
    """For non-books areas, _belongs_to_area is permissive."""
    music = {"source_name": "ナタリー音楽", "title": "x", "description": "y"}
    outdoor = {"source_name": "山と道 Journals", "title": "x", "description": "y"}
    ok = (
        leisure_recommender._belongs_to_area(music, "music") is True
        and leisure_recommender._belongs_to_area(outdoor, "outdoor") is True
    )
    _check("d4 music/outdoor: no source-based exclusion", ok)


# ---------------------------------------------------------------------------
# (e) Prompt building
# ---------------------------------------------------------------------------

def test_user_message_contains_article_fields():
    article = _sample_article()
    msg = leisure_recommender._build_column_user(article, "books")
    ok = (
        "テッド・チャン新短編集" in msg
        and "早川書房" in msg
        and "200〜300字" in msg
    )
    _check("e1 user message contains title + source + length rule", ok,
           f"first_60={msg[:60]!r}")


# ---------------------------------------------------------------------------
# Test runner
# ---------------------------------------------------------------------------

def main() -> int:
    print("Page 5 — leisure_recommender tests")
    print()
    print("(a) Column generation happy path:")
    test_generate_column_happy_path_books()
    test_generate_column_strips_code_fence()
    test_generate_column_eval_guide_in_system()
    print()
    print("(b) Column generation fallback paths:")
    test_generate_column_llm_exception_fallback()
    test_generate_column_non_json_fallback()
    test_generate_column_missing_keys_fallback()
    print()
    print("(c) recommend_for_area:")
    test_recommend_for_area_unsupported()
    test_recommend_for_area_no_candidates_returns_placeholder()
    print()
    print("(d) Books area filter (page3-R6 / page4 boundary):")
    test_books_filter_excludes_quanta()
    test_books_filter_excludes_aeon()
    test_books_filter_includes_hayakawa()
    test_music_outdoor_no_filter()
    print()
    print("(e) Prompt building:")
    test_user_message_contains_article_fields()
    print()
    print(f"=== {PASS} passed, {FAIL} failed ===")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
