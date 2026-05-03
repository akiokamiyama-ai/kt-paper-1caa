"""Unit tests for the title-only translation policy (Sprint 5, 2026-05-03).

Tests:
  a) EN article: title_ja is generated, desc_ja = description (passthrough)
  b) JA article: title_ja = title, desc_ja = description (no translation)
  c) source_language="en" is the primary signal (overrides JA-name heuristic)
  d) Missing source_language falls back to name heuristic
  e) translate_for_render logs "(title only)" for EN, "(JA passthrough)" for JA

Mock ``translate`` is used so we don't hit the network.

Run::

    python3 -m tests.test_translation_policy
"""

from __future__ import annotations

import io
import sys

from scripts import regen_front_page_v2 as regen

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


def _install_mock_translate():
    """Replace regen.translate with a deterministic mock."""
    calls: list[str] = []

    def mock_translate(text: str) -> str:
        calls.append(text)
        return f"[JA] {text}"

    original = regen.translate
    regen.translate = mock_translate
    return original, calls


def _restore_translate(original):
    regen.translate = original


# Patch out the sleep so tests run instantly.
def _install_no_sleep():
    import time
    original = time.sleep
    time.sleep = lambda *a, **kw: None
    return original


def _restore_sleep(original):
    import time
    time.sleep = original


# ---------------------------------------------------------------------------
# (a) EN article behavior
# ---------------------------------------------------------------------------

def test_en_article_title_translated_desc_passthrough():
    orig_t, calls = _install_mock_translate()
    orig_s = _install_no_sleep()
    try:
        article = {
            "title": "OpenAI launches new model",
            "description": "The model is faster and cheaper.",
            "source_name": "WIRED.com Backchannel",
            "source_language": "en",
        }
        regen._translate_article(article)
    finally:
        _restore_translate(orig_t)
        _restore_sleep(orig_s)
    title_ok = article["title_ja"] == "[JA] OpenAI launches new model"
    desc_ok = article["desc_ja"] == "The model is faster and cheaper."
    only_one_call = len(calls) == 1 and calls[0] == "OpenAI launches new model"
    _check("a1 EN article title is translated", title_ok,
           f"title_ja={article['title_ja']!r}")
    _check("a2 EN article desc is passthrough (= original description)", desc_ok,
           f"desc_ja={article['desc_ja']!r}")
    _check("a3 translate() called exactly once (title only)", only_one_call,
           f"calls={calls}")


# ---------------------------------------------------------------------------
# (b) JA article behavior
# ---------------------------------------------------------------------------

def test_ja_article_no_translation():
    orig_t, calls = _install_mock_translate()
    orig_s = _install_no_sleep()
    try:
        article = {
            "title": "経産省、生成AI導入参照アーキテクチャを公表",
            "description": "全92ページの文書...",
            "source_name": "経済産業省ニュースリリース",
            "source_language": "ja",
        }
        regen._translate_article(article)
    finally:
        _restore_translate(orig_t)
        _restore_sleep(orig_s)
    title_ok = article["title_ja"] == "経産省、生成AI導入参照アーキテクチャを公表"
    desc_ok = article["desc_ja"] == "全92ページの文書..."
    no_calls = len(calls) == 0
    _check("b1 JA article title_ja = original title (no translation)", title_ok)
    _check("b2 JA article desc_ja = original desc", desc_ok)
    _check("b3 translate() not called for JA articles", no_calls,
           f"calls={calls}")


# ---------------------------------------------------------------------------
# (c) source_language overrides heuristic
# ---------------------------------------------------------------------------

def test_source_language_en_overrides_ja_name_heuristic():
    """Source named '日本語っぽい' but tagged source_language='en' → translated."""
    orig_t, calls = _install_mock_translate()
    orig_s = _install_no_sleep()
    try:
        article = {
            "title": "Some English Title",
            "description": "English body.",
            "source_name": "日本語名のソース",  # JA-pattern in name
            "source_language": "en",  # but explicitly EN
        }
        regen._translate_article(article)
    finally:
        _restore_translate(orig_t)
        _restore_sleep(orig_s)
    _check("c1 source_language='en' overrides JA-name heuristic — title translated",
           article["title_ja"] == "[JA] Some English Title",
           f"title_ja={article['title_ja']!r}")


def test_source_language_ja_overrides_en_name_heuristic():
    """Source named English but tagged source_language='ja' → not translated."""
    orig_t, calls = _install_mock_translate()
    orig_s = _install_no_sleep()
    try:
        article = {
            "title": "日本語タイトル",
            "description": "日本語本文",
            "source_name": "Forbes Japan",  # name not matched by JA hira-kana heuristic without pattern
            "source_language": "ja",
        }
        regen._translate_article(article)
    finally:
        _restore_translate(orig_t)
        _restore_sleep(orig_s)
    _check("c2 source_language='ja' overrides — no translation",
           article["title_ja"] == "日本語タイトル" and len(calls) == 0,
           f"title_ja={article['title_ja']!r}, calls={calls}")


# ---------------------------------------------------------------------------
# (d) Fallback heuristic when source_language missing
# ---------------------------------------------------------------------------

def test_missing_source_language_uses_heuristic_for_en_name():
    """If source_language is missing, fall back to _is_japanese_source heuristic.

    EN-named source (no JA chars) → heuristic says EN → translate title.
    """
    orig_t, calls = _install_mock_translate()
    orig_s = _install_no_sleep()
    try:
        article = {
            "title": "Sloan Article",
            "description": "Original english.",
            "source_name": "MIT Sloan Management Review",
            # source_language MISSING — must trigger heuristic fallback
        }
        regen._translate_article(article)
    finally:
        _restore_translate(orig_t)
        _restore_sleep(orig_s)
    _check("d1 missing source_language + EN-named source → heuristic translates",
           article["title_ja"] == "[JA] Sloan Article" and len(calls) == 1,
           f"title_ja={article['title_ja']!r}, calls={calls}")


def test_missing_source_language_uses_heuristic_for_ja_name():
    """JA-named source with missing source_language → heuristic skips translation."""
    orig_t, calls = _install_mock_translate()
    orig_s = _install_no_sleep()
    try:
        article = {
            "title": "経産省ニュース",
            "description": "日本語本文",
            "source_name": "経済産業省ニュースリリース",
            # source_language MISSING
        }
        regen._translate_article(article)
    finally:
        _restore_translate(orig_t)
        _restore_sleep(orig_s)
    _check("d2 missing source_language + JA-named source → heuristic skips",
           article["title_ja"] == "経産省ニュース" and len(calls) == 0,
           f"title_ja={article['title_ja']!r}, calls={calls}")


# ---------------------------------------------------------------------------
# (e) translate_for_render log markers
# ---------------------------------------------------------------------------

def test_translate_for_render_log_markers():
    """translate_for_render prints '(title only)' for EN, '(JA passthrough)' for JA."""
    orig_t, _ = _install_mock_translate()
    orig_s = _install_no_sleep()
    captured = io.StringIO()
    original_stderr = sys.stderr
    sys.stderr = captured
    try:
        articles = [
            {
                "title": "EN1", "description": "d", "source_name": "BBC Business",
                "source_language": "en",
            },
            {
                "title": "JA1", "description": "d", "source_name": "Foresight",
                "source_language": "ja",
            },
        ]
        regen.translate_for_render(articles)
    finally:
        sys.stderr = original_stderr
        _restore_translate(orig_t)
        _restore_sleep(orig_s)
    log = captured.getvalue()
    en_marker_ok = "(title only)" in log
    ja_marker_ok = "(JA passthrough)" in log
    _check("e1 EN article logged with '(title only)' marker", en_marker_ok,
           f"log:\n{log}")
    _check("e2 JA article logged with '(JA passthrough)' marker", ja_marker_ok)


def main() -> int:
    print("Translation policy tests (Sprint 5, 2026-05-03)")
    print()
    print("(a) EN article — title translated, desc passthrough:")
    test_en_article_title_translated_desc_passthrough()
    print()
    print("(b) JA article — no translation:")
    test_ja_article_no_translation()
    print()
    print("(c) source_language overrides name heuristic:")
    test_source_language_en_overrides_ja_name_heuristic()
    test_source_language_ja_overrides_en_name_heuristic()
    print()
    print("(d) Fallback heuristic when source_language missing:")
    test_missing_source_language_uses_heuristic_for_en_name()
    test_missing_source_language_uses_heuristic_for_ja_name()
    print()
    print("(e) translate_for_render log markers:")
    test_translate_for_render_log_markers()
    print()
    print(f"=== {PASS} passed, {FAIL} failed ===")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
