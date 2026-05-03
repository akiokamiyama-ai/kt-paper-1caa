"""Unit tests for Source.language / Article.source_language (Sprint 5, 2026-05-03).

Tests:
  a) Source.language defaults to "ja" when unspecified
  b) sources/*.md `- **language**: en` gets parsed into Source.language="en"
  c) Article.source_language defaults to "ja"
  d) RSS driver propagates source.language → article.source_language
  e) Real registry: known EN sources have language="en", known JA stays "ja"

Run::

    python3 -m tests.lib.test_source_language
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from scripts.lib.source import (
    Article,
    Source,
    Status,
    Priority,
    FetchMethod,
    parse_sources_md,
)
from scripts.selector.source_registry import build_registry

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
# (a) Source default language
# ---------------------------------------------------------------------------

def test_source_language_default_ja():
    s = Source(
        name="Test", url="https://test.example/",
        category="test", priority=Priority.HIGH, status=Status.VERIFIED,
        fetch_method=FetchMethod.RSS,
    )
    _check("a1 Source.language default = 'ja'", s.language == "ja",
           f"got {s.language!r}")


def test_source_language_explicit_en():
    s = Source(
        name="Test", url="https://test.example/",
        category="test", priority=Priority.HIGH, status=Status.VERIFIED,
        fetch_method=FetchMethod.RSS, language="en",
    )
    _check("a2 Source.language='en' assignable", s.language == "en")


# ---------------------------------------------------------------------------
# (b) Parser reads `- **language**: en`
# ---------------------------------------------------------------------------

def test_parser_reads_language_en():
    md = """# Test sources

## High Priority

### 1. EN Source ✅
- **URL**: https://example.com/
- **RSS**: https://example.com/feed
- **language**: en
- **対象**: a foreign-language source
- **位置付け**: testing

### 2. JA Source ✅
- **URL**: https://例.jp/
- **RSS**: https://例.jp/feed
- **対象**: a Japanese source
- **位置付け**: testing
"""
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "test.md"
        path.write_text(md, encoding="utf-8")
        sources = parse_sources_md(path)
    by_name = {s.name: s for s in sources}
    _check("b1 EN-tagged source parses language='en'",
           by_name.get("EN Source") and by_name["EN Source"].language == "en",
           f"got {by_name.get('EN Source').language if by_name.get('EN Source') else 'NOT FOUND'!r}")
    _check("b2 untagged source defaults language='ja'",
           by_name.get("JA Source") and by_name["JA Source"].language == "ja",
           f"got {by_name.get('JA Source').language if by_name.get('JA Source') else 'NOT FOUND'!r}")


def test_parser_normalizes_language_value():
    """Misspelled or capitalized 'EN'/'English' should map to 'en'; anything else → 'ja'."""
    md = """## High Priority

### 1. Capital EN ✅
- **URL**: https://a.test/
- **RSS**: https://a.test/feed
- **language**: EN
- **対象**: t

### 2. Lowercase english ✅
- **URL**: https://b.test/
- **RSS**: https://b.test/feed
- **language**: english
- **対象**: t

### 3. Garbage ✅
- **URL**: https://c.test/
- **RSS**: https://c.test/feed
- **language**: nonsense
- **対象**: t
"""
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "test.md"
        path.write_text(md, encoding="utf-8")
        sources = parse_sources_md(path)
    by_name = {s.name: s for s in sources}
    _check("b3 'EN' (uppercase) → 'en'",
           by_name.get("Capital EN") and by_name["Capital EN"].language == "en")
    _check("b4 'english' → 'en'",
           by_name.get("Lowercase english") and by_name["Lowercase english"].language == "en")
    _check("b5 unknown value falls back to 'ja'",
           by_name.get("Garbage") and by_name["Garbage"].language == "ja",
           f"got {by_name.get('Garbage').language if by_name.get('Garbage') else 'NOT FOUND'!r}")


# ---------------------------------------------------------------------------
# (c) Article default source_language
# ---------------------------------------------------------------------------

def test_article_source_language_default_ja():
    a = Article(source_name="X", title="t", link="https://x/")
    _check("c1 Article.source_language default = 'ja'", a.source_language == "ja")


def test_article_source_language_assignable_en():
    a = Article(source_name="X", title="t", link="https://x/", source_language="en")
    _check("c2 Article.source_language='en' assignable", a.source_language == "en")


# ---------------------------------------------------------------------------
# (d) RSS driver propagates source.language
# ---------------------------------------------------------------------------

def test_rss_driver_propagates_language():
    """RssDriver._iter_items should set article.source_language=source.language."""
    from scripts.lib.drivers.rss import RssDriver
    import xml.etree.ElementTree as ET

    rss_xml = """<?xml version="1.0"?>
<rss version="2.0"><channel>
<item><title>T1</title><link>https://a.test/1</link><description>d</description><pubDate>Sat, 03 May 2026 09:00:00 +0900</pubDate></item>
</channel></rss>"""
    root = ET.fromstring(rss_xml)
    en_source = Source(
        name="ENTest", url="https://a.test/", category="test",
        priority=Priority.HIGH, status=Status.VERIFIED,
        fetch_method=FetchMethod.RSS, language="en",
    )
    arts = list(RssDriver._iter_items(root, en_source))
    _check("d1 RSS-derived Article inherits source.language='en'",
           len(arts) == 1 and arts[0].source_language == "en",
           f"got {arts[0].source_language!r}" if arts else "no articles")

    ja_source = Source(
        name="JATest", url="https://b.test/", category="test",
        priority=Priority.HIGH, status=Status.VERIFIED,
        fetch_method=FetchMethod.RSS,  # language defaults to "ja"
    )
    arts2 = list(RssDriver._iter_items(root, ja_source))
    _check("d2 RSS-derived Article inherits source.language='ja' (default)",
           len(arts2) == 1 and arts2[0].source_language == "ja")


# ---------------------------------------------------------------------------
# (e) Real registry sanity check
# ---------------------------------------------------------------------------

def test_real_registry_known_ja_sources():
    """Default language case: registry returns "ja" for unannotated sources.

    EN-tagging 検証は (B) commit で sources/*.md に language: en を追加した後の
    別コミットで補強する。本コミット (A) はパーサと dataclass の field 追加が
    主眼。
    """
    project_root = Path(__file__).resolve().parent.parent.parent
    sources_dir = project_root / "sources"
    if not sources_dir.exists():
        _check("e1 sources/ dir present", False, f"not found: {sources_dir}")
        return
    reg = build_registry(sources_dir)
    by_name = reg.sources_by_name
    known_ja = [
        "Foresight（新潮社）",
        "TABI LABO",
        "AXIS",
    ]
    ja_ok = all(by_name.get(n) and by_name[n].language == "ja" for n in known_ja)
    ja_detail = ", ".join(
        f"{n}={by_name[n].language!r}" if n in by_name else f"{n}=MISSING"
        for n in known_ja
    )
    _check("e1 known JA sources default to language='ja'", ja_ok, ja_detail)


def main() -> int:
    print("Source.language / Article.source_language tests (Sprint 5, 2026-05-03)")
    print()
    print("(a) Source default language:")
    test_source_language_default_ja()
    test_source_language_explicit_en()
    print()
    print("(b) Parser reads language field:")
    test_parser_reads_language_en()
    test_parser_normalizes_language_value()
    print()
    print("(c) Article default source_language:")
    test_article_source_language_default_ja()
    test_article_source_language_assignable_en()
    print()
    print("(d) RSS driver propagates language:")
    test_rss_driver_propagates_language()
    print()
    print("(e) Real registry sanity:")
    test_real_registry_known_ja_sources()
    print()
    print(f"=== {PASS} passed, {FAIL} failed ===")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
