"""Unit tests for scripts/source_allowlist.py (C81 段階 1).

Sprint 9 Fable レビュー M6 god module 分割の第一弾。Page I candidates / Today's
Headlines の allowlist を単一 source of truth で管理する仕組みを検証。

Run::

    python3 -m tests.test_source_allowlist
"""

from __future__ import annotations

import sys
from pathlib import Path

from scripts import source_allowlist as al

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
# (a) consistency between SOURCE_NAME_FILTERS and HEADLINES_ALLOWED_SOURCES
# ---------------------------------------------------------------------------

def test_allowlists_consistent():
    """check_allowlist_consistency() で不整合ゼロ."""
    issues = al.check_allowlist_consistency()
    _check(
        "a1 SOURCE_NAME_FILTERS と HEADLINES_ALLOWED_SOURCES が整合（unmatched 0 件）",
        issues == [],
        f"issues: {issues}",
    )


def test_every_headline_source_has_filter_prefix():
    """各 HEADLINES_ALLOWED_SOURCES が SOURCE_NAME_FILTERS のいずれかの substring を含む.

    C78 真因「page1 candidates に流入していない source は Headlines pool に
    届かない」の構造的予防。
    """
    failures: list[str] = []
    for h in al.HEADLINES_ALLOWED_SOURCES:
        if not any(f in h for f in al.SOURCE_NAME_FILTERS):
            failures.append(h)
    _check(
        "a2 各 Headlines source は SOURCE_NAME_FILTERS prefix を含む",
        failures == [],
        f"unreachable: {failures}",
    )


def test_category_restrict_keys_in_headlines():
    """HEADLINES_SOURCE_CATEGORY_RESTRICT の key が HEADLINES_ALLOWED_SOURCES に含まれる."""
    failures: list[str] = []
    for k in al.HEADLINES_SOURCE_CATEGORY_RESTRICT:
        if k not in al.HEADLINES_ALLOWED_SOURCES:
            failures.append(k)
    _check(
        "a3 category restrict の key は allowlist に存在する（無効 restriction 0 件）",
        failures == [],
        f"orphan: {failures}",
    )


# ---------------------------------------------------------------------------
# (b) registry-level reachability（実 sources/*.md と突合）
# ---------------------------------------------------------------------------

def test_headlines_sources_resolve_in_registry():
    """HEADLINES_ALLOWED_SOURCES の全 source.name が SourceRegistry に存在する."""
    from scripts.selector.source_registry import build_registry
    reg = build_registry(Path(__file__).resolve().parent.parent / "sources")
    missing = [
        name for name in al.HEADLINES_ALLOWED_SOURCES
        if name not in reg.sources_by_name
    ]
    _check(
        "b1 HEADLINES_ALLOWED_SOURCES の全件が SourceRegistry に存在",
        missing == [],
        f"missing: {missing}",
    )


def test_source_name_filters_hit_at_least_one_source():
    """SOURCE_NAME_FILTERS の各 substring が少なくとも 1 source にヒットする."""
    from scripts.fetch import load_all_sources
    sources = load_all_sources(Path(__file__).resolve().parent.parent / "sources")
    failures: list[str] = []
    for f in al.SOURCE_NAME_FILTERS:
        hit = any(f.lower() in s.name.lower() for s in sources)
        if not hit:
            failures.append(f)
    _check(
        "b2 各 SOURCE_NAME_FILTERS substring が少なくとも 1 source にヒット",
        failures == [],
        f"unmatched: {failures}",
    )


# ---------------------------------------------------------------------------
# (c) backward compat re-export from old modules
# ---------------------------------------------------------------------------

def test_regen_front_page_v2_reexports_source_name_filters():
    """旧 import path 維持: from scripts.regen_front_page_v2 import SOURCE_NAME_FILTERS."""
    from scripts.regen_front_page_v2 import SOURCE_NAME_FILTERS as snf
    _check(
        "c1 regen_front_page_v2.SOURCE_NAME_FILTERS は source_allowlist と同一 object",
        snf is al.SOURCE_NAME_FILTERS,
    )


def test_todays_headlines_reexports_allowlists():
    from scripts.selector.todays_headlines import (
        HEADLINES_ALLOWED_SOURCES as has,
        HEADLINES_SOURCE_CATEGORY_RESTRICT as hsr,
    )
    _check(
        "c2 todays_headlines.HEADLINES_ALLOWED_SOURCES re-export 一致",
        has is al.HEADLINES_ALLOWED_SOURCES,
    )
    _check(
        "c3 todays_headlines.HEADLINES_SOURCE_CATEGORY_RESTRICT re-export 一致",
        hsr is al.HEADLINES_SOURCE_CATEGORY_RESTRICT,
    )


def main() -> int:
    print("source_allowlist unit tests (C81 段階 1, Fable review M6)")
    print()
    print("(a) consistency:")
    test_allowlists_consistent()
    test_every_headline_source_has_filter_prefix()
    test_category_restrict_keys_in_headlines()
    print()
    print("(b) registry-level reachability:")
    test_headlines_sources_resolve_in_registry()
    test_source_name_filters_hit_at_least_one_source()
    print()
    print("(c) backward-compat re-export:")
    test_regen_front_page_v2_reexports_source_name_filters()
    test_todays_headlines_reexports_allowlists()
    print()
    print(f"=== {PASS} passed, {FAIL} failed ===")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
