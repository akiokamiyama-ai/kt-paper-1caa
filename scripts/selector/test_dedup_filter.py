"""Unit tests for scripts/selector/dedup_filter.py.

Run::

    python3 -m scripts.selector.test_dedup_filter

Tests use a tmp directory by monkeypatching ``LOG_DIR`` so the real
``logs/`` is never touched.
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

from . import dedup_filter

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


class _TempLogDir:
    """Context manager that points dedup_filter.LOG_DIR at a fresh tmpdir."""

    def __enter__(self):
        self.tmpdir = Path(tempfile.mkdtemp(prefix="dedup_test_"))
        self._original = dedup_filter.LOG_DIR
        dedup_filter.LOG_DIR = self.tmpdir
        return self.tmpdir

    def __exit__(self, *exc):
        dedup_filter.LOG_DIR = self._original
        shutil.rmtree(self.tmpdir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_write_and_read():
    """write → load roundtrip."""
    with _TempLogDir():
        target = date(2026, 4, 30)
        path = dedup_filter.write_displayed_urls_log(
            target,
            page1_urls=["https://a.test/1", "https://a.test/2"],
            page2_urls_by_company={"cocolomi": "https://b.test/c", "human_energy": None, "web_repo": "https://b.test/w"},
        )
        ok = path.exists()
        log = dedup_filter.load_displayed_urls_log(target)
        ok &= log is not None
        ok &= log["date"] == "2026-04-30"
        ok &= log["page1_urls"] == ["https://a.test/1", "https://a.test/2"]
        ok &= log["page2_urls"]["cocolomi"] == "https://b.test/c"
        ok &= log["page2_urls"]["human_energy"] is None
        _check("d1 write → load roundtrip", ok)


def test_load_missing_returns_none():
    """Missing log file returns None, no crash."""
    with _TempLogDir():
        log = dedup_filter.load_displayed_urls_log(date(2025, 1, 1))
        _check("d2 missing log → None", log is None)


def test_load_recently_page1_window():
    """page='page1' collects all URLs from the window [target-days_back, target-1]."""
    with _TempLogDir():
        target = date(2026, 5, 1)
        # Write 4/29 and 4/30 (last 2 days)
        dedup_filter.write_displayed_urls_log(
            date(2026, 4, 29),
            page1_urls=["url-29-a", "url-29-b", "url-29-c", "url-29-d"],
            page2_urls_by_company={},
        )
        dedup_filter.write_displayed_urls_log(
            date(2026, 4, 30),
            page1_urls=["url-30-a", "url-30-b", "url-30-c", "url-30-d"],
            page2_urls_by_company={},
        )
        # Today (5/1) should NOT be included even if exists.
        dedup_filter.write_displayed_urls_log(
            target,
            page1_urls=["url-01-a"],
            page2_urls_by_company={},
        )
        urls = dedup_filter.load_recently_displayed_urls(
            days_back=7, page="page1", until_date=target,
        )
        expected = {f"url-{d}-{x}" for d in ("29", "30") for x in "abcd"}
        ok = urls == expected
        _check(
            "d3 page1: 7-day window collects 4/29 + 4/30, excludes 5/1 itself",
            ok,
            f"got {len(urls)} urls, expected {len(expected)}",
        )


def test_load_recently_page2_per_company():
    """page='page2' with company_key collects only that company's URLs."""
    with _TempLogDir():
        target = date(2026, 5, 1)
        for d, urls in [
            (date(2026, 4, 29), {"cocolomi": "co-29", "human_energy": "he-29", "web_repo": None}),
            (date(2026, 4, 30), {"cocolomi": "co-30", "human_energy": "he-30", "web_repo": "wr-30"}),
        ]:
            dedup_filter.write_displayed_urls_log(d, page1_urls=[], page2_urls_by_company=urls)
        cocolomi = dedup_filter.load_recently_displayed_urls(
            days_back=3, page="page2", company_key="cocolomi", until_date=target,
        )
        web_repo = dedup_filter.load_recently_displayed_urls(
            days_back=3, page="page2", company_key="web_repo", until_date=target,
        )
        # web_repo only has wr-30 (29 was None)
        ok = (cocolomi == {"co-29", "co-30"} and web_repo == {"wr-30"})
        _check("d4 page2 per-company: skips None entries", ok,
               f"cocolomi={cocolomi}, web_repo={web_repo}")


def test_load_recently_window_truncation():
    """days_back=3 only walks 3 days, even if older logs exist."""
    with _TempLogDir():
        target = date(2026, 5, 1)
        # Write a log 5 days back (4/26)
        dedup_filter.write_displayed_urls_log(
            date(2026, 4, 26),
            page1_urls=["url-26"],
            page2_urls_by_company={},
        )
        # And 2 days back (4/29)
        dedup_filter.write_displayed_urls_log(
            date(2026, 4, 29),
            page1_urls=["url-29"],
            page2_urls_by_company={},
        )
        # days_back=3 should include 4/29 (2 days back) but NOT 4/26 (5 days back)
        urls = dedup_filter.load_recently_displayed_urls(
            days_back=3, page="page1", until_date=target,
        )
        ok = urls == {"url-29"}
        _check("d5 days_back=3 truncates older logs", ok, f"got {urls}")


def test_filter_recently_displayed():
    """filter_recently_displayed removes matching URLs, preserves order."""
    articles = [
        {"url": "u1", "title": "A"},
        {"url": "u2", "title": "B"},
        {"url": "u3", "title": "C"},
        {"url": "u4", "title": "D"},
        {"title": "no-url"},  # missing url field — should be kept
    ]
    displayed = {"u1", "u3"}
    filtered = dedup_filter.filter_recently_displayed(articles, displayed)
    ok = (
        [a.get("url") for a in filtered] == ["u2", "u4", None]
        and len(filtered) == 3
    )
    _check("d6 filter removes matching URLs, keeps urlless articles", ok)


def test_filter_empty_displayed():
    """Empty displayed_urls = identity passthrough."""
    articles = [{"url": "u1"}, {"url": "u2"}]
    filtered = dedup_filter.filter_recently_displayed(articles, set())
    ok = filtered == articles and filtered is not articles
    _check("d7 filter with empty displayed = identity (copy)", ok)


def main() -> int:
    print("Dedup filter unit tests")
    print()
    test_write_and_read()
    test_load_missing_returns_none()
    test_load_recently_page1_window()
    test_load_recently_page2_per_company()
    test_load_recently_window_truncation()
    test_filter_recently_displayed()
    test_filter_empty_displayed()
    print()
    print(f"=== {PASS} passed, {FAIL} failed ===")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
