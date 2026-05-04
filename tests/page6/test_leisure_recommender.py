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
# (f) Sprint 5 task #4: focus_work field (2026-05-04)
# ---------------------------------------------------------------------------

import json as _json


def test_focus_work_in_response_extracted():
    """LLM が focus_work を返す → return dict に正しく入る。"""
    payload = _json.dumps({
        "column_title": "ボカロが大西洋を渡る日",
        "focus_work": "『愛して愛して愛して』 / きくお",
        "column_body": "Yeの長女ノース・ウェストが1st EPに収録した楽曲が、ボカロP・きくおの『愛して愛して愛して』をサンプリングしているという。",
    }, ensure_ascii=False)
    with _StubLLM(text=payload):
        result, cost, is_fallback = leisure_recommender._generate_column("music", _sample_article())
    _check("f1 focus_work present in response → extracted",
           result.get("focus_work") == "『愛して愛して愛して』 / きくお"
           and is_fallback is False,
           f"got focus_work={result.get('focus_work')!r}, is_fallback={is_fallback}")


def test_focus_work_missing_in_response_defaults_to_empty():
    """LLM が focus_work キーを返さない → 空文字列。"""
    payload = _json.dumps({
        "column_title": "Title",
        "column_body": "本文の一段落、200字以上の十分な長さ。" + "あ" * 100,
        # focus_work missing
    }, ensure_ascii=False)
    with _StubLLM(text=payload):
        result, cost, is_fallback = leisure_recommender._generate_column("books", _sample_article())
    _check("f2 focus_work missing → empty string",
           result.get("focus_work") == "" and is_fallback is False,
           f"got focus_work={result.get('focus_work')!r}")


def test_focus_work_empty_string_preserved():
    """LLM が focus_work='' を返す → そのまま空文字列（HTML 側で <p> 省略）。"""
    payload = _json.dumps({
        "column_title": "T",
        "focus_work": "",
        "column_body": "本文" + "あ" * 100,
    }, ensure_ascii=False)
    with _StubLLM(text=payload):
        result, _cost, is_fallback = leisure_recommender._generate_column("outdoor", _sample_article())
    _check("f3 focus_work='' preserved",
           result.get("focus_work") == "" and is_fallback is False)


def test_focus_work_non_string_treated_as_empty():
    """LLM が focus_work に文字列以外を返す → 空文字列に正規化。"""
    payload = _json.dumps({
        "column_title": "T",
        "focus_work": ["array", "not", "string"],  # 不正
        "column_body": "本文" + "あ" * 100,
    }, ensure_ascii=False)
    with _StubLLM(text=payload):
        result, _cost, _is_fallback = leisure_recommender._generate_column("books", _sample_article())
    _check("f4 non-string focus_work → ''", result.get("focus_work") == "")


def test_description_fallback_includes_empty_focus_work():
    """LLM 失敗時の fallback でも focus_work=空文字列キーが入る。"""
    fb = leisure_recommender._description_fallback(_sample_article())
    _check("f5 fallback dict has focus_work key set to ''",
           "focus_work" in fb and fb["focus_work"] == "")


def test_user_message_includes_focus_work_format():
    """COLUMN_PROMPT_TEMPLATE の {focus_work_format} が領域別に正しく差し込まれる。"""
    msg_books = leisure_recommender._build_column_user(_sample_article(), "books")
    msg_music = leisure_recommender._build_column_user(_sample_article(), "music")
    msg_outdoor = leisure_recommender._build_column_user(_sample_article(), "outdoor")
    _check("f6 books prompt: 「『本タイトル』 著者名」",
           "本タイトル" in msg_books and "著者名" in msg_books)
    _check("f7 music prompt: 「『曲名/アルバム名』 / アーティスト名」",
           "曲名" in msg_music and "アーティスト名" in msg_music)
    _check("f8 outdoor prompt: 「場所 / トレイル名」",
           "場所" in msg_outdoor and "トレイル名" in msg_outdoor)


def test_user_message_requires_focus_work_in_output():
    """JSON フォーマット指示に focus_work が含まれる。"""
    msg = leisure_recommender._build_column_user(_sample_article(), "books")
    _check("f9 user message asks for 'focus_work' in JSON output",
           '"focus_work"' in msg)


def test_focus_work_format_constants_defined():
    """FOCUS_WORK_FORMAT_BY_AREA に 3 area 全部のキーがある。"""
    fmt_map = prompts.FOCUS_WORK_FORMAT_BY_AREA
    _check("f10 FOCUS_WORK_FORMAT_BY_AREA has all 3 areas",
           set(fmt_map.keys()) == {"books", "music", "outdoor"})


def test_render_leisure_column_with_focus_work():
    """regen_v2._render_leisure_column: focus_work あり → <p class="focus-work"> 出力。"""
    from scripts import regen_front_page_v2 as regen
    result = {
        "column_title": "ボカロが大西洋を渡る日",
        "focus_work": "『愛して愛して愛して』 / きくお",
        "column_body": "Yeの長女ノース・ウェスト...",
        "article": {
            "source_name": "Pitchfork",
            "url": "https://example.test/article",
            "pub_date": "2026-05-03",
        },
    }
    html = regen._render_leisure_column(
        area_label="音楽", column_class="music-column-v2", result=result,
    )
    has_focus = (
        '<p class="focus-work">'
        in html and "『愛して愛して愛して』 / きくお" in html
    )
    placement_ok = html.find("focus-work") < html.find("column-body")
    _check("f11 focus_work → <p class='focus-work'> rendered above column-body",
           has_focus and placement_ok)


def test_render_leisure_column_without_focus_work():
    """focus_work='' → <p class="focus-work"> が出力されない（紙面構造保持）。"""
    from scripts import regen_front_page_v2 as regen
    result = {
        "column_title": "T",
        "focus_work": "",
        "column_body": "B",
        "article": {
            "source_name": "S",
            "url": "https://example.test/article",
            "pub_date": "2026-05-03",
        },
    }
    html = regen._render_leisure_column(
        area_label="読書", column_class="books-column-v2", result=result,
    )
    _check("f12 focus_work='' → no <p class='focus-work'> in HTML",
           "focus-work" not in html)


def test_focus_work_css_present_in_page_six_css():
    """PAGE_SIX_CSS に .focus-work セレクタが含まれる。"""
    from scripts import regen_front_page_v2 as regen
    css = regen.PAGE_SIX_CSS
    _check("f13 .focus-work CSS rule present",
           ".leisure-column-v2 .focus-work" in css)


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
    print("(f) Sprint 5 task #4: focus_work field:")
    test_focus_work_in_response_extracted()
    test_focus_work_missing_in_response_defaults_to_empty()
    test_focus_work_empty_string_preserved()
    test_focus_work_non_string_treated_as_empty()
    test_description_fallback_includes_empty_focus_work()
    test_user_message_includes_focus_work_format()
    test_user_message_requires_focus_work_in_output()
    test_focus_work_format_constants_defined()
    test_render_leisure_column_with_focus_work()
    test_render_leisure_column_without_focus_work()
    test_focus_work_css_present_in_page_six_css()
    print()
    print(f"=== {PASS} passed, {FAIL} failed ===")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
