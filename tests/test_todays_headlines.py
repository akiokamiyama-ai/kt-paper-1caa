"""Unit tests for todays_headlines (Sprint 7 Phase 2 Step 1, 2026-05-19).

Tests:
  a) excluded_urls 除外 (Page I + Page III)
  b) eligible_sources フィルタ
  c) final_score 降順 + top_n
  d) format_summary：100 字以内 / 超過 / 空 description
  e) candidates_scored 空 → 空リスト
  f) 全候補 excluded → 空リスト
  g) page3_selections の article 取得（dataclass + dict 両形式）
  h) HEADLINES_ALLOWED_SOURCES の構成検証

Run::

    python3 -m tests.test_todays_headlines
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import date

from scripts.selector.todays_headlines import (
    BODY_MIN_CHARS,
    DEFAULT_HEADLINES_TOP_N,
    DEFAULT_SUMMARY_MAX_CHARS,
    HEADLINES_ALLOWED_SOURCES,
    HEADLINES_DEDUP_DAYS,
    LLM_SUMMARY_MAX_CHARS,
    format_summary,
    generate_summary_with_llm,
    select_todays_headlines,
)

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


def _make_article(
    url: str,
    *,
    source: str = "BBC Business",
    score: float | None = 50.0,
    description: str = "デフォルト description 100 字未満のサンプル文",
) -> dict:
    return {
        "url": url,
        "title": f"title for {url}",
        "source_name": source,
        "final_score": score,
        "description": description,
    }


# ---------------------------------------------------------------------------
# (a) excluded_urls 除外
# ---------------------------------------------------------------------------

def test_excluded_page1():
    candidates = [
        _make_article("https://a/1", score=90),
        _make_article("https://a/2", score=80),
    ]
    page1_selected = [{"url": "https://a/1"}]
    result = select_todays_headlines(
        target_date=date(2026, 5, 19),
        candidates_scored=candidates,
        page1_selected=page1_selected,
    )
    _check(
        "a1 Page I 採用 URL を除外",
        len(result) == 1 and result[0]["url"] == "https://a/2",
        f"got {[r['url'] for r in result]}",
    )


def test_excluded_page3_dataclass():
    @dataclass
    class _RegSel:
        article: dict | None
    candidates = [
        _make_article("https://a/1", score=90),
        _make_article("https://a/2", score=80),
    ]
    page3 = {
        "R1": _RegSel(article={"url": "https://a/1"}),
        "R2": _RegSel(article=None),
    }
    result = select_todays_headlines(
        target_date=date(2026, 5, 19),
        candidates_scored=candidates,
        page3_selections=page3,
    )
    _check(
        "a2 Page III 採用 URL (dataclass) を除外",
        len(result) == 1 and result[0]["url"] == "https://a/2",
        f"got {[r['url'] for r in result]}",
    )


def test_excluded_page3_dict():
    candidates = [_make_article("https://a/1", score=90),
                  _make_article("https://a/2", score=80)]
    page3 = {"R1": {"article": {"url": "https://a/1"}}}
    result = select_todays_headlines(
        target_date=date(2026, 5, 19),
        candidates_scored=candidates,
        page3_selections=page3,
    )
    _check(
        "a3 Page III 採用 URL (dict 形式) を除外",
        len(result) == 1 and result[0]["url"] == "https://a/2",
    )


# ---------------------------------------------------------------------------
# (b) eligible_sources フィルタ
# ---------------------------------------------------------------------------

def test_source_filter_allowed():
    candidates = [
        _make_article("https://nhk/", source="NHK ニュース 主要"),
        _make_article("https://bbc/", source="BBC Business"),
        _make_article("https://other/", source="Forbes Japan（リーダーシップ・組織論）"),
        _make_article("https://music/", source="natalie.mu"),
    ]
    result = select_todays_headlines(
        target_date=date(2026, 5, 19),
        candidates_scored=candidates,
    )
    urls = {r["url"] for r in result}
    _check(
        "b1 許可ソースのみ（NHK + BBC）が選定、Forbes/music は除外",
        urls == {"https://nhk/", "https://bbc/"},
        f"got {urls}",
    )


def test_source_filter_custom():
    candidates = [
        _make_article("https://x/", source="X"),
        _make_article("https://y/", source="Y"),
    ]
    result = select_todays_headlines(
        target_date=date(2026, 5, 19),
        candidates_scored=candidates,
        eligible_sources=("X",),
    )
    _check(
        "b2 custom eligible_sources=('X',) で X のみ採用",
        len(result) == 1 and result[0]["source_name"] == "X",
    )


# ---------------------------------------------------------------------------
# (c) final_score 降順 + top_n
# ---------------------------------------------------------------------------

def test_score_descending_and_top_n():
    candidates = [
        _make_article(f"https://x/{i}", score=100 - i,
                      source="NHK ニュース 主要")
        for i in range(10)
    ]
    result = select_todays_headlines(
        target_date=date(2026, 5, 19),
        candidates_scored=candidates,
        top_n=3,
    )
    urls = [r["url"] for r in result]
    _check(
        "c1 top_n=3 で score 降順 (100,99,98)",
        urls == ["https://x/0", "https://x/1", "https://x/2"],
        f"got {urls}",
    )


def test_top_n_default():
    _check(
        "c2 DEFAULT_HEADLINES_TOP_N == 3",
        DEFAULT_HEADLINES_TOP_N == 3,
    )


# ---------------------------------------------------------------------------
# (d) format_summary
# ---------------------------------------------------------------------------

def test_summary_short_passthrough():
    art = {"description": "短い description サンプル文"}
    s = format_summary(art)
    _check(
        "d1 200 字以内はそのまま返す（Sprint 7 微調整 100→200）",
        s == "短い description サンプル文",
        f"got {s!r}",
    )


def test_summary_long_truncate():
    art = {"description": "あ" * 400}
    s = format_summary(art)
    _check(
        "d2 200 字超は末尾「…」付き truncate（Sprint 7 微調整）",
        len(s) == 200 and s.endswith("…"),
        f"got len={len(s)}, ends={s[-3:]!r}",
    )


def test_summary_empty_description():
    """Yahoo! 等の title-only feed 用：description 空なら空文字列."""
    _check(
        "d3 description 欠落 → 空文字列",
        format_summary({}) == "",
    )
    _check(
        "d4 description=None → 空文字列",
        format_summary({"description": None}) == "",
    )
    _check(
        "d5 description=空白のみ → 空文字列",
        format_summary({"description": "   \n  "}) == "",
    )


def test_summary_default_max_chars():
    _check(
        "d6 DEFAULT_SUMMARY_MAX_CHARS == 200 (Sprint 7 微調整、5/19 神山さん観察)",
        DEFAULT_SUMMARY_MAX_CHARS == 200,
    )


def test_summary_custom_max_chars():
    art = {"description": "1234567890"}
    _check(
        "d7 max_chars=5 で truncate（末尾「…」、4 文字本文）",
        format_summary(art, max_chars=5) == "1234…",
        f"got {format_summary(art, max_chars=5)!r}",
    )


# ---------------------------------------------------------------------------
# (e) candidates_scored 空 → 空リスト
# ---------------------------------------------------------------------------

def test_empty_candidates():
    _check(
        "e1 candidates_scored 空 → 空リスト",
        select_todays_headlines(
            target_date=date(2026, 5, 19),
            candidates_scored=[],
        ) == [],
    )


# ---------------------------------------------------------------------------
# (f) 全候補 excluded → 空リスト
# ---------------------------------------------------------------------------

def test_all_excluded():
    candidates = [
        _make_article("https://a/1", source="NHK ニュース 主要"),
        _make_article("https://a/2", source="NHK ニュース 主要"),
    ]
    page1 = [{"url": "https://a/1"}, {"url": "https://a/2"}]
    _check(
        "f1 全候補が Page I 採用済み → 空リスト",
        select_todays_headlines(
            target_date=date(2026, 5, 19),
            candidates_scored=candidates,
            page1_selected=page1,
        ) == [],
    )


def test_all_filtered_out_by_source():
    candidates = [
        _make_article("https://x/", source="Music News"),
        _make_article("https://y/", source="Cooking Site"),
    ]
    _check(
        "f2 全候補が許可外 source → 空リスト",
        select_todays_headlines(
            target_date=date(2026, 5, 19),
            candidates_scored=candidates,
        ) == [],
    )


# ---------------------------------------------------------------------------
# (g) HEADLINES_ALLOWED_SOURCES の構成検証
# ---------------------------------------------------------------------------

def test_allowed_sources_contents():
    # C75 (Sprint 9, 2026-06-10): SOURCE_NAME_FILTERS と整合し FT を追加。
    expected_keys = {
        "NHK ニュース 主要",
        "NHK ニュース 経済",
        "Yahoo! ニュース 経済",
        "BBC Business",
        "The Economist",
        "Financial Times（FT）",
    }
    _check(
        "g1 HEADLINES_ALLOWED_SOURCES 6 件、全 expected 名を含む（C75: FT 追加）",
        set(HEADLINES_ALLOWED_SOURCES) == expected_keys,
        f"got {set(HEADLINES_ALLOWED_SOURCES)}",
    )


def test_allowed_sources_match_registry():
    """business.md にこれらの名前で source が登録されていることを確認."""
    from pathlib import Path
    from scripts.selector.source_registry import build_registry
    reg = build_registry(Path("/home/akiok/projects/tribune/sources"))
    missing = [
        name for name in HEADLINES_ALLOWED_SOURCES
        if name not in reg.sources_by_name
    ]
    _check(
        "g2 全 HEADLINES_ALLOWED_SOURCES が SourceRegistry に存在",
        not missing,
        f"missing={missing}" if missing else "all present",
    )


# ---------------------------------------------------------------------------
# (h) generate_summary_with_llm（C14 対処, Sprint 8, 2026-05-20）
#     body_fetcher / llm_caller を mock し、ネットワーク・LLM 無しで検証。
# ---------------------------------------------------------------------------

_LONG_BODY = "あ" * (BODY_MIN_CHARS + 100)  # 本文取得成功の十分な長さ


def test_llm_summary_success():
    art = {"url": "https://www.bbc.com/news/x", "title": "T", "source_name": "BBC Business",
           "description": "短い RSS description"}
    out = generate_summary_with_llm(
        art,
        body_fetcher=lambda url: _LONG_BODY,
        llm_caller=lambda t, s, b: "Haiku が生成した 200 字相当の要約テキスト。",
    )
    _check(
        "h1 本文取得 + LLM 成功 → LLM 要約を返す",
        out == "Haiku が生成した 200 字相当の要約テキスト。",
        f"got {out!r}",
    )


def test_llm_summary_fallback_empty_body():
    """BBC 以外 / 本文取得不可 → body_fetcher が空 → format_summary fallback."""
    art = {"url": "https://nhk.example/x", "title": "T", "source_name": "NHK ニュース 経済",
           "description": "NHK の RSS description"}
    out = generate_summary_with_llm(
        art, body_fetcher=lambda url: "", llm_caller=lambda t, s, b: "使われないはず",
    )
    _check(
        "h2 本文空（BBC 以外）→ format_summary fallback",
        out == "NHK の RSS description", f"got {out!r}",
    )


def test_llm_summary_fallback_short_body():
    """本文が BODY_MIN_CHARS 未満 → LLM 呼ばず fallback."""
    art = {"url": "https://www.bbc.com/news/x", "source_name": "BBC Business",
           "description": "RSS desc"}
    out = generate_summary_with_llm(
        art, body_fetcher=lambda url: "短い", llm_caller=lambda t, s, b: "使われないはず",
    )
    _check("h3 本文短すぎ → fallback", out == "RSS desc", f"got {out!r}")


def test_llm_summary_fallback_llm_raises():
    """LLM 呼び出しが例外（cap 超過・API 失敗等）→ fallback."""
    def _boom(t, s, b):
        raise RuntimeError("API down")
    art = {"url": "https://www.bbc.com/news/x", "description": "RSS desc fallback"}
    out = generate_summary_with_llm(art, body_fetcher=lambda url: _LONG_BODY, llm_caller=_boom)
    _check("h4 LLM 例外 → fallback", out == "RSS desc fallback", f"got {out!r}")


def test_llm_summary_fallback_fetch_raises():
    """本文取得が例外 → fallback."""
    def _boom(url):
        raise ConnectionError("network down")
    art = {"url": "https://www.bbc.com/news/x", "description": "RSS desc fallback"}
    out = generate_summary_with_llm(art, body_fetcher=_boom, llm_caller=lambda t, s, b: "x")
    _check("h5 本文取得例外 → fallback", out == "RSS desc fallback", f"got {out!r}")


def test_llm_summary_runaway_truncated():
    """LLM が暴走して長文を返した → LLM_SUMMARY_MAX_CHARS で truncate."""
    art = {"url": "https://www.bbc.com/news/x", "description": "RSS desc"}
    out = generate_summary_with_llm(
        art, body_fetcher=lambda url: _LONG_BODY,
        llm_caller=lambda t, s, b: "暴" * 500,
    )
    _check(
        "h6 LLM 暴走長文 → LLM_SUMMARY_MAX_CHARS で truncate（末尾…）",
        len(out) == LLM_SUMMARY_MAX_CHARS and out.endswith("…"),
        f"got len={len(out)}",
    )


def test_llm_summary_no_url():
    """url 無し → fallback."""
    art = {"description": "RSS desc no url"}
    out = generate_summary_with_llm(
        art, body_fetcher=lambda url: _LONG_BODY, llm_caller=lambda t, s, b: "x",
    )
    _check("h7 url 無し → fallback", out == "RSS desc no url", f"got {out!r}")


def test_llm_summary_empty_llm_output():
    """LLM が空文字列を返した → fallback."""
    art = {"url": "https://www.bbc.com/news/x", "description": "RSS desc"}
    out = generate_summary_with_llm(
        art, body_fetcher=lambda url: _LONG_BODY, llm_caller=lambda t, s, b: "   ",
    )
    _check("h8 LLM 空出力 → fallback", out == "RSS desc", f"got {out!r}")


# ---------------------------------------------------------------------------
# (i) C40 recency dedup（Sprint 8, 2026-05-28）
#
# 5/27-5/28 で BBC が同 URL (cwy22rddy5no) のままタイトルを更新し、headlines に
# 2 日連続で表示された事例。案 1 で displayed_urls に headlines_urls を記録、
# 案 2 で select_todays_headlines に過去 7 日分の URL set を渡して除外する。
# ---------------------------------------------------------------------------

def test_recent_dedup_excludes_seen_url():
    """過去 N 日分 displayed_urls に含まれる URL は除外される（C40 真因対策）."""
    candidates = [
        _make_article("https://bbc.com/x/cwy22rddy5no", score=90, source="BBC Business"),
        _make_article("https://bbc.com/x/other",      score=80, source="BBC Business"),
    ]
    result = select_todays_headlines(
        target_date=date(2026, 5, 28),
        candidates_scored=candidates,
        recent_displayed_urls={"https://bbc.com/x/cwy22rddy5no"},
    )
    _check(
        "i1 過去 displayed_urls にある URL を除外（同 URL タイトル更新 case）",
        len(result) == 1 and result[0]["url"] == "https://bbc.com/x/other",
        f"got {[r['url'] for r in result]}",
    )


def test_recent_dedup_passes_unseen_url():
    """過去履歴に無い URL はそのまま通過."""
    candidates = [
        _make_article("https://new/1", score=90, source="BBC Business"),
        _make_article("https://new/2", score=80, source="BBC Business"),
    ]
    result = select_todays_headlines(
        target_date=date(2026, 5, 28),
        candidates_scored=candidates,
        recent_displayed_urls={"https://old/never-seen"},
    )
    urls = {r["url"] for r in result}
    _check(
        "i2 過去 displayed_urls に無い URL は通過",
        urls == {"https://new/1", "https://new/2"},
        f"got {urls}",
    )


def test_recent_dedup_none_is_noop():
    """recent_displayed_urls=None なら Sprint 7 までの挙動と等価（後方互換）."""
    candidates = [
        _make_article("https://a/1", score=90, source="BBC Business"),
        _make_article("https://a/2", score=80, source="BBC Business"),
    ]
    result = select_todays_headlines(
        target_date=date(2026, 5, 28),
        candidates_scored=candidates,
        # recent_displayed_urls 省略 → None
    )
    _check(
        "i3 recent_displayed_urls 省略 → recency dedup 無し（後方互換）",
        len(result) == 2,
        f"got {len(result)} items",
    )


def test_recent_dedup_empty_set_is_noop():
    """空 set でも recency dedup 無し（窓内に何も displayed されていない初日扱い）."""
    candidates = [_make_article("https://a/1", score=90, source="BBC Business")]
    result = select_todays_headlines(
        target_date=date(2026, 5, 28),
        candidates_scored=candidates,
        recent_displayed_urls=set(),
    )
    _check(
        "i4 recent_displayed_urls=空 set → 全候補通過",
        len(result) == 1,
    )


def test_recent_dedup_combines_with_page1_3_exclusion():
    """recent_displayed_urls は page1_selected / page3_selections と OR 結合."""
    candidates = [
        _make_article("https://a/1", score=90, source="BBC Business"),  # page1 除外
        _make_article("https://a/2", score=80, source="BBC Business"),  # past 除外
        _make_article("https://a/3", score=70, source="BBC Business"),  # 通過
    ]
    result = select_todays_headlines(
        target_date=date(2026, 5, 28),
        candidates_scored=candidates,
        page1_selected=[{"url": "https://a/1"}],
        recent_displayed_urls={"https://a/2"},
    )
    _check(
        "i5 page1 除外 + recency 除外が両方効く（OR 結合）",
        len(result) == 1 and result[0]["url"] == "https://a/3",
        f"got {[r['url'] for r in result]}",
    )


def test_headlines_dedup_days_constant():
    """HEADLINES_DEDUP_DAYS=7（神山さん指定: PAGE2_DEDUP_DAYS=3 より長め）."""
    _check(
        "i6 HEADLINES_DEDUP_DAYS == 7（同 URL の 1 週間以内の再表示を禁止、"
        "2 週間以上前は再評価許容）",
        HEADLINES_DEDUP_DAYS == 7,
        f"got {HEADLINES_DEDUP_DAYS}",
    )


def test_recent_dedup_window_boundary_via_loader():
    """load_recently_displayed_urls が window=7 で境界日を正しく扱うか（統合テスト）.

    target=5/29 で window=7 → 5/22-5/28 が対象、5/21 と 5/29 は対象外。
    """
    import json
    import tempfile
    from pathlib import Path

    from scripts.selector import dedup_filter

    orig_log_dir = dedup_filter.LOG_DIR
    with tempfile.TemporaryDirectory() as tmp:
        dedup_filter.LOG_DIR = Path(tmp)
        try:
            # window 内（5/22, 5/28）に記録
            for d, url in [("2026-05-22", "https://within/early"),
                           ("2026-05-28", "https://within/recent")]:
                (Path(tmp) / f"displayed_urls_{d}.json").write_text(json.dumps({
                    "date": d, "headlines_urls": [url],
                }))
            # window 外（5/21）に記録 — 取らない
            (Path(tmp) / "displayed_urls_2026-05-21.json").write_text(json.dumps({
                "date": "2026-05-21", "headlines_urls": ["https://outside/past"],
            }))
            # 当日（5/29）に記録 — 取らない（target 自身は除外）
            (Path(tmp) / "displayed_urls_2026-05-29.json").write_text(json.dumps({
                "date": "2026-05-29", "headlines_urls": ["https://outside/today"],
            }))

            urls = dedup_filter.load_recently_displayed_urls(
                HEADLINES_DEDUP_DAYS, page="headlines", until_date=date(2026, 5, 29),
            )
            _check(
                "i7 window=7 で 5/22-5/28 のみ収集（5/21 と 5/29 は範囲外）",
                urls == {"https://within/early", "https://within/recent"},
                f"got {sorted(urls)}",
            )
        finally:
            dedup_filter.LOG_DIR = orig_log_dir


def test_old_log_without_headlines_field_safe():
    """5/28 以前の旧ログ（headlines_urls フィールド不在）でも crash しない."""
    import json
    import tempfile
    from pathlib import Path

    from scripts.selector import dedup_filter

    orig_log_dir = dedup_filter.LOG_DIR
    with tempfile.TemporaryDirectory() as tmp:
        dedup_filter.LOG_DIR = Path(tmp)
        try:
            # 旧形式：headlines_urls フィールド無し
            (Path(tmp) / "displayed_urls_2026-05-25.json").write_text(json.dumps({
                "date": "2026-05-25", "page1_urls": ["https://p1/x"],
            }))
            urls = dedup_filter.load_recently_displayed_urls(
                7, page="headlines", until_date=date(2026, 5, 28),
            )
            _check(
                "i8 旧ログ (headlines_urls 欠落) → 空 set、crash しない",
                urls == set(),
                f"got {urls}",
            )
        finally:
            dedup_filter.LOG_DIR = orig_log_dir


def main() -> int:
    print("Today's Headlines selector tests (Sprint 7 Phase 2 Step 1, 2026-05-19)")
    print()
    print("(a) excluded_urls 除外:")
    test_excluded_page1()
    test_excluded_page3_dataclass()
    test_excluded_page3_dict()
    print()
    print("(b) eligible_sources フィルタ:")
    test_source_filter_allowed()
    test_source_filter_custom()
    print()
    print("(c) final_score 降順 + top_n:")
    test_score_descending_and_top_n()
    test_top_n_default()
    print()
    print("(d) format_summary:")
    test_summary_short_passthrough()
    test_summary_long_truncate()
    test_summary_empty_description()
    test_summary_default_max_chars()
    test_summary_custom_max_chars()
    print()
    print("(e) candidates_scored 空:")
    test_empty_candidates()
    print()
    print("(f) 全候補 excluded / filtered:")
    test_all_excluded()
    test_all_filtered_out_by_source()
    print()
    print("(g) HEADLINES_ALLOWED_SOURCES 検証:")
    test_allowed_sources_contents()
    test_allowed_sources_match_registry()
    print()
    print("(h) generate_summary_with_llm（C14 対処）:")
    test_llm_summary_success()
    test_llm_summary_fallback_empty_body()
    test_llm_summary_fallback_short_body()
    test_llm_summary_fallback_llm_raises()
    test_llm_summary_fallback_fetch_raises()
    test_llm_summary_runaway_truncated()
    test_llm_summary_no_url()
    test_llm_summary_empty_llm_output()
    print()
    print("(i) C40 recency dedup（Sprint 8, 2026-05-28）:")
    test_recent_dedup_excludes_seen_url()
    test_recent_dedup_passes_unseen_url()
    test_recent_dedup_none_is_noop()
    test_recent_dedup_empty_set_is_noop()
    test_recent_dedup_combines_with_page1_3_exclusion()
    test_headlines_dedup_days_constant()
    test_recent_dedup_window_boundary_via_loader()
    test_old_log_without_headlines_field_safe()
    print()
    print(f"=== {PASS} passed, {FAIL} failed ===")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
