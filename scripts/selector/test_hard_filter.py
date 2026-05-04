"""Unit tests for hard_filter.py — focuses on the Podcast exclusion path
added in Sprint 2 Step C.

Run with::

    python3 -m scripts.selector.test_hard_filter

The existing region-based hard filters (books / SF / companies / outdoor)
are exercised indirectly via test_page2.py and the larger smoke tests.
This file specifically validates the universal Podcast / audio-content
filter and its integration with run_stage1.
"""

from __future__ import annotations

import sys

from . import hard_filter
from .stage1 import run_stage1


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


# ---------------------------------------------------------------------------
# Direct evaluate_podcast() tests
# ---------------------------------------------------------------------------

def test_podcast_url_hbr():
    """HBR Podcast URL → excluded."""
    excluded, reason = hard_filter.evaluate_podcast(
        url="https://hbr.org/podcast/2026/04/why-your-team-wont-speak-up-and-how-to-fix-it",
        title="Why Your Team Won’t Speak Up (And How to Fix It)",
        description="A conversation with author Charles Duhigg about creating an open culture.",
    )
    ok = excluded is True and reason == "podcast_or_audio_content"
    _check("p1 HBR /podcast/ URL → excluded", ok,
           f"excluded={excluded}, reason={reason!r}")


def test_podcast_normal_article():
    """通常記事（Podcast 言及なし）→ NOT excluded."""
    excluded, reason = hard_filter.evaluate_podcast(
        url="https://www.economist.com/finance-and-economics/2026/04/26/article-slug",
        title="Banking rules tightened across G7",
        description="Regulators move on capital adequacy after recent failures.",
    )
    ok = excluded is False and reason is None
    _check("p2 通常記事 → NOT excluded", ok,
           f"excluded={excluded}, reason={reason!r}")


def test_podcast_japanese_title():
    """title に「ポッドキャスト」を含む → excluded."""
    excluded, reason = hard_filter.evaluate_podcast(
        url="https://example.test/article/123",
        title="新作ポッドキャストで語られる組織開発論",
        description="経営者向けの音声番組。",
    )
    ok = excluded is True and reason == "podcast_or_audio_content"
    _check("p3 title に「ポッドキャスト」→ excluded", ok,
           f"excluded={excluded}, reason={reason!r}")


def test_podcast_audio_marker():
    """description に [Audio] 記法を含む → excluded."""
    excluded, reason = hard_filter.evaluate_podcast(
        url="https://example.test/article/abc",
        title="Strategy Talk",
        description="[Audio] Interview with leadership researcher Edgar Schein.",
    )
    ok = excluded is True and reason == "podcast_or_audio_content"
    _check("p4 description に [Audio] → excluded", ok,
           f"excluded={excluded}, reason={reason!r}")


def test_podcast_spotify_url():
    """spotify.com/episode/... → excluded（外部ポッドキャストプラットフォーム）。"""
    excluded, reason = hard_filter.evaluate_podcast(
        url="https://open.spotify.com/episode/abc123def456",
        title="Some episode title",
        description="...",
    )
    ok = excluded is True and reason == "podcast_or_audio_content"
    _check("p5 spotify.com/episode → excluded", ok,
           f"excluded={excluded}, reason={reason!r}")


# ---------------------------------------------------------------------------
# Integration tests via run_stage1
# ---------------------------------------------------------------------------

def test_stage1_excludes_podcast():
    """run_stage1 が Podcast URL の記事を is_excluded=True で返す."""
    articles = [
        {
            "url": "https://hbr.org/podcast/2026/04/why-your-team-wont-speak-up-and-how-to-fix-it",
            "title": "Why Your Team Won’t Speak Up (And How to Fix It)",
            "description": "A conversation with author Charles Duhigg about creating an open culture.",
            "body": "",
            "source_name": "Harvard Business Review（HBR.org）",
        },
        {
            "url": "https://hbr.org/2026/04/normal-article-here",
            "title": "Why Some Teams Outperform Others",
            "description": "A long-form essay on team dynamics in modern organizations." * 2,
            "body": "",
            "source_name": "Harvard Business Review（HBR.org）",
        },
    ]
    out = run_stage1(articles)
    pod = out[0]
    normal = out[1]
    pod_ok = (
        pod.get("is_excluded") is True
        and pod.get("exclusion_reason") == "podcast_or_audio_content"
    )
    normal_ok = normal.get("is_excluded") is False
    _check(
        "p6 stage1: HBR /podcast/ URL → is_excluded=True, normal HBR article → NOT excluded",
        pod_ok and normal_ok,
        f"pod={pod.get('is_excluded')}/{pod.get('exclusion_reason')!r}, "
        f"normal={normal.get('is_excluded')}",
    )


# ---------------------------------------------------------------------------
# Direct evaluate_description_length() tests (Sprint 3 Step A)
# ---------------------------------------------------------------------------

def test_desclen_none():
    excluded, reason = hard_filter.evaluate_description_length({"description": None})
    ok = excluded is True and reason == "description_too_short"
    _check("d1 None description → excluded", ok,
           f"excluded={excluded}, reason={reason!r}")


def test_desclen_empty():
    excluded, reason = hard_filter.evaluate_description_length({"description": ""})
    ok = excluded is True and reason == "description_too_short"
    _check("d2 empty description → excluded", ok,
           f"excluded={excluded}, reason={reason!r}")


def test_desclen_29_chars():
    excluded, reason = hard_filter.evaluate_description_length({"description": "a" * 29})
    ok = excluded is True and reason == "description_too_short"
    _check("d3 29-char description → excluded", ok,
           f"excluded={excluded}, reason={reason!r}")


def test_desclen_30_chars():
    """境界値：30 文字ちょうど → NOT excluded."""
    excluded, reason = hard_filter.evaluate_description_length({"description": "a" * 30})
    ok = excluded is False and reason is None
    _check("d4 30-char description → NOT excluded (boundary)", ok,
           f"excluded={excluded}, reason={reason!r}")


def test_desclen_100_chars():
    excluded, reason = hard_filter.evaluate_description_length({"description": "a" * 100})
    ok = excluded is False and reason is None
    _check("d5 100-char description → NOT excluded", ok)


def test_desclen_whitespace_only():
    """全部 whitespace → strip 後 0 文字 → excluded."""
    excluded, reason = hard_filter.evaluate_description_length({"description": "   \n\t  "})
    ok = excluded is True and reason == "description_too_short"
    _check("d6 whitespace-only description → excluded", ok,
           f"excluded={excluded}, reason={reason!r}")


def test_stage1_excludes_short_description():
    """run_stage1 integration: 日経風の短い description は除外される."""
    arts = [
        {
            "url": "https://www.nikkei.com/article/short-desc",
            "title": "Apple、1~3月純利益19%増　際限なき「AI軍拡競争」とは一線",
            "description": "",  # 日経 RSS の典型例
            "body": "",
            "source_name": "日本経済新聞",
        },
        {
            "url": "https://www.economist.com/full-desc",
            "title": "Banking rules tightened across G7",
            "description": "G7 finance ministers agreed yesterday to tighten capital requirements for systemically important banks following the latest Basel review.",
            "body": "",
            "source_name": "The Economist",
        },
    ]
    out = run_stage1(arts)
    short = next(a for a in out if "short-desc" in a["url"])
    full = next(a for a in out if "full-desc" in a["url"])
    ok = (
        short.get("is_excluded") is True
        and short.get("exclusion_reason") == "description_too_short"
        and full.get("is_excluded") is False
    )
    _check(
        "d7 stage1: empty description → excluded, full description → NOT excluded",
        ok,
        f"short={short.get('is_excluded')}/{short.get('exclusion_reason')!r}, "
        f"full={full.get('is_excluded')}",
    )


# ---------------------------------------------------------------------------
# Sprint 5 task #1 (2026-05-04): description_exempt for title-only feeds
# ---------------------------------------------------------------------------

def _patch_site_config(overrides: dict):
    """Helper: install a stub SiteConfig so we don't read the real TOML."""
    from ..lib.drivers.base import SiteConfig
    hard_filter._SITE_CONFIG_CACHE = SiteConfig(overrides=overrides)


def _restore_site_config():
    hard_filter._reset_site_config_cache_for_tests()


def test_desclen_asahi_exempt_passes():
    """www.asahi.com is in description_exempt list → empty desc passes Stage 1."""
    _patch_site_config({"www.asahi.com": {"description_exempt": True}})
    try:
        article = {
            "url": "https://www.asahi.com/articles/ASV5412BTV54ULFA003M.html",
            "title": "ロシア産原油、ホルムズ封鎖後初の調達 制裁適用外のサハリン2から",
            "description": "",
        }
        excluded, reason = hard_filter.evaluate_description_length(article)
    finally:
        _restore_site_config()
    _check("e1 asahi.com (description_exempt) + empty desc → NOT excluded",
           excluded is False and reason is None,
           f"excluded={excluded}, reason={reason}")


def test_desclen_nikkei_not_exempt_excluded():
    """assets.wor.jp is NOT in exempt list → empty desc excluded (Nikkei behavior)."""
    _patch_site_config({"www.asahi.com": {"description_exempt": True}})
    try:
        article = {
            "url": "https://www.nikkei.com/article/DGXZQOUC30ADB0Q6A430C2000000/",
            "title": "テーマパークに新施設続々　体験レジャーの最前線がわかる10選",
            "description": "",
        }
        excluded, reason = hard_filter.evaluate_description_length(article)
    finally:
        _restore_site_config()
    _check("e2 nikkei.com (NOT exempt) + empty desc → excluded",
           excluded is True and reason == "description_too_short")


def test_desclen_other_host_normal_filter_still_works():
    """Hosts not in the override map still use the 30-char threshold."""
    _patch_site_config({"www.asahi.com": {"description_exempt": True}})
    try:
        article = {
            "url": "https://example.test/short",
            "title": "Some title",
            "description": "too short",
        }
        excluded, reason = hard_filter.evaluate_description_length(article)
    finally:
        _restore_site_config()
    _check("e3 unmapped host + short desc → normal exclusion",
           excluded is True and reason == "description_too_short")


def test_desclen_no_url_falls_back_to_normal_check():
    """Article without URL (rare) falls back to normal description-length check."""
    _patch_site_config({"www.asahi.com": {"description_exempt": True}})
    try:
        article = {"title": "T", "description": ""}  # no url
        excluded, reason = hard_filter.evaluate_description_length(article)
    finally:
        _restore_site_config()
    _check("e4 no URL + empty desc → excluded (normal path)",
           excluded is True and reason == "description_too_short")


def test_desclen_empty_overrides_normal_filter_unchanged():
    """No exempt list configured → existing behavior unchanged."""
    _patch_site_config({})  # no description_exempt anywhere
    try:
        article = {
            "url": "https://www.asahi.com/articles/x",
            "title": "T",
            "description": "",
        }
        excluded, reason = hard_filter.evaluate_description_length(article)
    finally:
        _restore_site_config()
    _check("e5 empty overrides → asahi gets normal filter (excluded)",
           excluded is True and reason == "description_too_short")


def test_desclen_exempt_with_existing_long_desc():
    """Exempt host with normal-length desc also passes (descriptions are not required to be empty)."""
    _patch_site_config({"www.asahi.com": {"description_exempt": True}})
    try:
        article = {
            "url": "https://www.asahi.com/x",
            "title": "T",
            "description": "これは普通の長さの description です。30文字以上あります。",
        }
        excluded, reason = hard_filter.evaluate_description_length(article)
    finally:
        _restore_site_config()
    _check("e6 exempt host + long desc → still passes",
           excluded is False and reason is None)


# ---------------------------------------------------------------------------
# Test runner
# ---------------------------------------------------------------------------

def main() -> int:
    print("Hard filter — Podcast / audio-content tests + description length")
    print()
    print("(p) evaluate_podcast() direct:")
    test_podcast_url_hbr()
    test_podcast_normal_article()
    test_podcast_japanese_title()
    test_podcast_audio_marker()
    test_podcast_spotify_url()
    print()
    print("(p) run_stage1 integration:")
    test_stage1_excludes_podcast()
    print()
    print("(d) evaluate_description_length() direct + stage1:")
    test_desclen_none()
    test_desclen_empty()
    test_desclen_29_chars()
    test_desclen_30_chars()
    test_desclen_100_chars()
    test_desclen_whitespace_only()
    test_stage1_excludes_short_description()
    print()
    print("(e) Sprint 5 task #1: description_exempt for title-only feeds:")
    test_desclen_asahi_exempt_passes()
    test_desclen_nikkei_not_exempt_excluded()
    test_desclen_other_host_normal_filter_still_works()
    test_desclen_no_url_falls_back_to_normal_check()
    test_desclen_empty_overrides_normal_filter_unchanged()
    test_desclen_exempt_with_existing_long_desc()
    print()
    print(f"=== {PASS} passed, {FAIL} failed ===")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
