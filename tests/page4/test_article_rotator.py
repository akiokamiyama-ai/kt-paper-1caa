"""Unit tests for scripts/page4/article_rotator.py.

Run::

    python3 -m tests.page4.test_article_rotator

These tests focus on PURE LOGIC — HUMANITIES_IMPRINTS filter, rotation
expiry, persistence — without hitting the real fetch + Stage 2 pipeline.
"""

from __future__ import annotations

import json
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

from scripts.page4 import article_rotator

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
# (a) HUMANITIES_IMPRINTS filter — substring matching
# ---------------------------------------------------------------------------

def test_humanities_iwanami_shoten():
    _check("a1 '岩波書店' matches",
           article_rotator.is_humanities("岩波書店") is True)


def test_humanities_iwanami_shinsho():
    """ユーザー仕様例：「岩波新書」→ ヒット（"岩波" が含まれる）.

    実装メモ：仕様書原文では HUMANITIES_IMPRINTS キーが "岩波書店" だったが、
    "岩波書店" は "岩波新書" の部分文字列ではないので、その通りだと
    fail する。神山さんの意図に沿って "岩波" 単独に修正してある。"""
    _check("a2 '岩波新書' matches via '岩波' key",
           article_rotator.is_humanities("岩波新書") is True)


def test_humanities_iwanami_gendai_bunko():
    _check("a2b '岩波現代文庫' matches",
           article_rotator.is_humanities("岩波現代文庫") is True)


def test_humanities_chikuma_shinsho():
    _check("a3 'ちくま新書' matches", article_rotator.is_humanities("ちくま新書") is True)


def test_humanities_chikuma_gakugei_bunko():
    _check("a4 'ちくま学芸文庫' matches",
           article_rotator.is_humanities("ちくま学芸文庫") is True)


def test_humanities_kadokawa_sophia_bunko():
    _check("a5 '角川ソフィア文庫' matches",
           article_rotator.is_humanities("角川ソフィア文庫") is True)


def test_humanities_kadokawa_bunko_does_not_match():
    """角川文庫 is fiction-mainstream, not in HUMANITIES_IMPRINTS."""
    _check("a6 '角川文庫' does NOT match",
           article_rotator.is_humanities("角川文庫") is False)


def test_humanities_blue_backs_does_not_match():
    """Blue Backs is a science series (page3 R6), not page4."""
    _check("a7 'ブルーバックス' does NOT match (page3 R6 territory)",
           article_rotator.is_humanities("ブルーバックス") is False)


def test_humanities_kodansha_alone_does_not_match():
    """Bare 講談社 (no specific imprint) doesn't match — too broad."""
    _check("a8 '講談社' alone does NOT match",
           article_rotator.is_humanities("講談社") is False)


def test_humanities_kodansha_gakujutsu_matches():
    _check("a9 '講談社学術文庫' matches",
           article_rotator.is_humanities("講談社学術文庫") is True)


def test_humanities_none_returns_false():
    _check("a10 None / empty returns False",
           article_rotator.is_humanities(None) is False
           and article_rotator.is_humanities("") is False)


def test_humanities_misuzu_shobo():
    _check("a11 'みすず書房' matches",
           article_rotator.is_humanities("みすず書房") is True)


# ---------------------------------------------------------------------------
# (b) Rotation expiry logic
# ---------------------------------------------------------------------------

def test_pool_active_future_expiry():
    today = date(2026, 5, 1)
    rotation = {
        "pool": ["url1", "url2", "url3"],
        "expires_on": (today + timedelta(days=2)).isoformat(),
        "generated_on": today.isoformat(),
    }
    _check("b1 pool active when expires_on > today",
           article_rotator.is_pool_active(rotation, today) is True)


def test_pool_active_today_expiry():
    today = date(2026, 5, 1)
    rotation = {
        "pool": ["url1"], "expires_on": today.isoformat(),
        "generated_on": today.isoformat(),
    }
    # expires_on == today → still active (>= today)
    _check("b2 pool active when expires_on == today",
           article_rotator.is_pool_active(rotation, today) is True)


def test_pool_inactive_past_expiry():
    today = date(2026, 5, 1)
    rotation = {
        "pool": ["url1"],
        "expires_on": (today - timedelta(days=1)).isoformat(),
        "generated_on": (today - timedelta(days=4)).isoformat(),
    }
    _check("b3 pool inactive when expires_on < today",
           article_rotator.is_pool_active(rotation, today) is False)


def test_pool_inactive_no_expires_on():
    today = date(2026, 5, 1)
    rotation = {"pool": [], "expires_on": None, "generated_on": None}
    _check("b4 pool inactive when expires_on is None",
           article_rotator.is_pool_active(rotation, today) is False)


def test_pool_inactive_malformed_date():
    today = date(2026, 5, 1)
    rotation = {"pool": [], "expires_on": "not-a-date", "generated_on": None}
    _check("b5 pool inactive on malformed expires_on",
           article_rotator.is_pool_active(rotation, today) is False)


# ---------------------------------------------------------------------------
# (c) Rotation persistence (load/save roundtrip via tmp file)
# ---------------------------------------------------------------------------

def test_rotation_save_load_roundtrip():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "page4_rotation.json"
        rotation = {
            "pool": ["url1", "url2", "url3"],
            "expires_on": "2026-05-04",
            "generated_on": "2026-05-01",
        }
        article_rotator.save_rotation(rotation, path=path)
        loaded = article_rotator.load_rotation(path=path)
    ok = loaded["pool"] == ["url1", "url2", "url3"] and loaded["expires_on"] == "2026-05-04"
    _check("c1 save/load roundtrip preserves pool + expires_on", ok,
           f"loaded={loaded}")


def test_rotation_load_missing_returns_empty():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "nonexistent.json"
        loaded = article_rotator.load_rotation(path=path)
    _check("c2 missing rotation file → empty dict",
           loaded == {"pool": [], "expires_on": None, "generated_on": None},
           f"got {loaded}")


def test_rotation_load_corrupt_returns_empty():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "rotation.json"
        path.write_text("not valid json {{{")
        loaded = article_rotator.load_rotation(path=path)
    _check("c3 corrupt JSON → empty dict (no crash)",
           loaded == {"pool": [], "expires_on": None, "generated_on": None})


# ---------------------------------------------------------------------------
# (d) Single-fetch invariant — v1.1 fix for the 5/2 duplicate-fetch bug
# ---------------------------------------------------------------------------

class _FetchCounter:
    """Monkey-patch ``article_rotator._fetch_and_score_humanities`` and
    record how many times it is invoked.

    Use as a context manager. ``return_articles`` are returned every call,
    ``return_cost`` is summed by the caller.
    """

    def __init__(self, return_articles: list[dict] | None = None,
                 return_cost: float = 0.0):
        self.return_articles = return_articles or []
        self.return_cost = return_cost
        self.call_count = 0
        self._original = None

    def __enter__(self):
        self._original = article_rotator._fetch_and_score_humanities

        def _stub(*, pre_evaluated=None, registry=None):
            self.call_count += 1
            return list(self.return_articles), self.return_cost

        article_rotator._fetch_and_score_humanities = _stub
        return self

    def __exit__(self, *exc):
        article_rotator._fetch_and_score_humanities = self._original


def _toy_articles(urls: list[str]) -> list[dict]:
    return [
        {"url": u, "title": f"t-{u}", "description": "x" * 80,
         "source_name": "春秋社", "category": "academic",
         "final_score": 50.0 - i, "美意識1": 5}
        for i, u in enumerate(urls)
    ]


def test_d1_empty_pool_with_future_expiry_fetches_once():
    """The 5/2 bug: pool=[] + expires_on=future was fetching twice.
    After v1.1 fix → fetches exactly once via _generate_new_pool."""
    today = date(2026, 5, 2)
    rotation = {
        "pool": [],
        "expires_on": (today + timedelta(days=2)).isoformat(),
        "generated_on": (today - timedelta(days=1)).isoformat(),
    }
    fetched = _toy_articles(["u1", "u2", "u3", "u4", "u5"])
    with _FetchCounter(return_articles=fetched, return_cost=0.08) as fc:
        result = article_rotator.get_today_articles(
            target_date=today, rotation=rotation, persist=False,
        )
    ok = (
        fc.call_count == 1
        and result["from_cache"] is False
        and len(result["articles"]) == 3
    )
    _check(
        "d1 empty pool + future expiry → fetches ONCE (was 2 in 5/2 bug)",
        ok,
        f"fetch_count={fc.call_count}, from_cache={result['from_cache']}, "
        f"n_articles={len(result['articles'])}",
    )


def test_d2_empty_pool_no_expiry_fetches_once():
    today = date(2026, 5, 2)
    rotation = {"pool": [], "expires_on": None, "generated_on": None}
    fetched = _toy_articles(["u1", "u2", "u3"])
    with _FetchCounter(return_articles=fetched) as fc:
        result = article_rotator.get_today_articles(
            target_date=today, rotation=rotation, persist=False,
        )
    ok = fc.call_count == 1 and result["from_cache"] is False
    _check(
        "d2 empty pool + no expiry → fetches ONCE (regenerate path)",
        ok,
        f"fetch_count={fc.call_count}, from_cache={result['from_cache']}",
    )


def test_d3_active_pool_uses_cache_one_fetch():
    today = date(2026, 5, 2)
    rotation = {
        "pool": ["u1", "u2", "u3"],
        "expires_on": (today + timedelta(days=1)).isoformat(),
        "generated_on": (today - timedelta(days=1)).isoformat(),
    }
    # Mock fetch returns the 3 pool URLs (so they match) plus extras.
    fetched = _toy_articles(["u1", "u2", "u3", "u4", "u5"])
    with _FetchCounter(return_articles=fetched) as fc:
        result = article_rotator.get_today_articles(
            target_date=today, rotation=rotation, persist=False,
        )
    ok = (
        fc.call_count == 1
        and result["from_cache"] is True
        and [a["url"] for a in result["articles"]] == ["u1", "u2", "u3"]
    )
    _check(
        "d3 active pool (3 URLs + future expiry) → fetches ONCE via cache rebuild",
        ok,
        f"fetch_count={fc.call_count}, from_cache={result['from_cache']}, "
        f"urls={[a['url'] for a in result['articles']]}",
    )


def test_d4_expired_pool_regenerates_one_fetch():
    today = date(2026, 5, 2)
    rotation = {
        "pool": ["u1", "u2", "u3"],
        "expires_on": (today - timedelta(days=1)).isoformat(),
        "generated_on": (today - timedelta(days=4)).isoformat(),
    }
    fetched = _toy_articles(["v1", "v2", "v3"])
    with _FetchCounter(return_articles=fetched) as fc:
        result = article_rotator.get_today_articles(
            target_date=today, rotation=rotation, persist=False,
        )
    ok = (
        fc.call_count == 1
        and result["from_cache"] is False
        and [a["url"] for a in result["articles"]] == ["v1", "v2", "v3"]
    )
    _check(
        "d4 non-empty pool but expired → fetches ONCE via regenerate",
        ok,
        f"fetch_count={fc.call_count}, from_cache={result['from_cache']}",
    )


def test_d5_is_pool_active_empty_pool_returns_false():
    """Direct invariant: empty pool is no longer 'active' even with future expiry."""
    today = date(2026, 5, 2)
    rotation = {
        "pool": [],
        "expires_on": (today + timedelta(days=10)).isoformat(),
    }
    _check(
        "d5 is_pool_active([], future) → False (v1.1 invariant)",
        article_rotator.is_pool_active(rotation, today) is False,
    )


# ---------------------------------------------------------------------------
# Test runner
# ---------------------------------------------------------------------------

def main() -> int:
    print("Page 4 — article_rotator tests")
    print()
    print("(a) HUMANITIES_IMPRINTS filter:")
    test_humanities_iwanami_shoten()
    test_humanities_iwanami_shinsho()
    test_humanities_iwanami_gendai_bunko()
    test_humanities_chikuma_shinsho()
    test_humanities_chikuma_gakugei_bunko()
    test_humanities_kadokawa_sophia_bunko()
    test_humanities_kadokawa_bunko_does_not_match()
    test_humanities_blue_backs_does_not_match()
    test_humanities_kodansha_alone_does_not_match()
    test_humanities_kodansha_gakujutsu_matches()
    test_humanities_none_returns_false()
    test_humanities_misuzu_shobo()
    print()
    print("(b) Rotation expiry logic:")
    test_pool_active_future_expiry()
    test_pool_active_today_expiry()
    test_pool_inactive_past_expiry()
    test_pool_inactive_no_expires_on()
    test_pool_inactive_malformed_date()
    print()
    print("(c) Rotation persistence:")
    test_rotation_save_load_roundtrip()
    test_rotation_load_missing_returns_empty()
    test_rotation_load_corrupt_returns_empty()
    print()
    print("(d) Single-fetch invariant (v1.1 5/2 bug fix):")
    test_d1_empty_pool_with_future_expiry_fetches_once()
    test_d2_empty_pool_no_expiry_fetches_once()
    test_d3_active_pool_uses_cache_one_fetch()
    test_d4_expired_pool_regenerates_one_fetch()
    test_d5_is_pool_active_empty_pool_returns_false()
    print()
    print(f"=== {PASS} passed, {FAIL} failed ===")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
