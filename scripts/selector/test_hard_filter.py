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
# Test runner
# ---------------------------------------------------------------------------

def main() -> int:
    print("Hard filter — Podcast / audio-content tests")
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
    print(f"=== {PASS} passed, {FAIL} failed ===")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
