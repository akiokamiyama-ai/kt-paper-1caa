"""Region-aware hard filters per news_profile.md §5.2.

The categories below mirror the ``Source.category`` values produced by the
markdown parser:

* ``books``                       — base; all books sub-categories share romance/light-novel filters
* ``books:SF``                    — SF sub-category; cyberpunk/space-opera filter is **title-only**
* ``companies:Cocolomi``          — competitor company-name filter (stub list, refine over time)
* ``companies:Human Energy``      — same idea, kept empty (LLM Stage 2 will judge)
* ``outdoor``                     — hardcore-mountaineering technical-jargon filter

§5.2 also lists Web-Repo (FC事業) — no hard filter is documented for it,
so we omit that region.

The function returns ``(excluded, reason)``; reason explains which rule
fired so logs/scores entries are debuggable.
"""

from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# Pattern banks
# ---------------------------------------------------------------------------

_BOOKS_ROMANCE: list[re.Pattern[str]] = [
    re.compile(r"恋愛小説"),
    re.compile(r"ラブストーリー"),
    re.compile(r"ライトノベル"),
    re.compile(r"ラノベ"),
    re.compile(r"ロマンス小説"),
    re.compile(r"ボーイズラブ"),
    re.compile(r"ティーンズラブ"),
]

_BOOKS_SF_TITLE_ONLY: list[re.Pattern[str]] = [
    re.compile(r"サイバーパンク"),
    re.compile(r"スペースオペラ"),
    re.compile(r"cyberpunk", re.IGNORECASE),
    re.compile(r"\bspace\s*opera\b", re.IGNORECASE),
]

# Phase 2 Sprint 1 暫定リスト。神山さんの感覚で精査・拡張する想定で、
# 一般的に名前が挙がる生成AI導入支援ベンダーに留める。Latin word boundaries
# (\b) do not work cleanly when adjacent to Japanese hiragana — Python's
# `\b` treats hiragana as word characters — so we use ASCII-only lookarounds.
_LB = r"(?<![A-Za-z0-9])"
_RB = r"(?![A-Za-z0-9])"
_COCOLOMI_COMPETITORS: list[re.Pattern[str]] = [
    re.compile(_LB + r"ABEJA" + _RB, re.IGNORECASE),
    re.compile(_LB + r"ELYZA" + _RB, re.IGNORECASE),
    re.compile(r"エクサウィザーズ"),
    re.compile(_LB + r"Exa\s*Wizards" + _RB, re.IGNORECASE),
    re.compile(_LB + r"PKSHA" + _RB, re.IGNORECASE),
    re.compile(r"パークシャ"),
    re.compile(_LB + r"AI\s*inside" + _RB, re.IGNORECASE),
    re.compile(_LB + r"Cinnamon\s*AI" + _RB, re.IGNORECASE),
    re.compile(_LB + r"Preferred\s*Networks" + _RB, re.IGNORECASE),
]

# 同業の営業戦略・拡大路線は具体キーワードで弾きにくいので、Stage 1 では
# 空にして Stage 2 (LLM) の判断に委ねる。
_HUMAN_ENERGY_COMPETITORS: list[re.Pattern[str]] = []

_OUTDOOR_HARDCORE: list[re.Pattern[str]] = [
    re.compile(r"アルパインクライミング"),
    re.compile(r"冬季縦走"),
    re.compile(r"ロープ確保"),
    re.compile(r"ピッケルワーク"),
    re.compile(r"アイゼンワーク"),
    re.compile(r"フリークライミング"),
    re.compile(r"バリエーションルート"),
]


def _fire(label: str, patterns: list[re.Pattern[str]], text: str) -> str | None:
    if not text or not patterns:
        return None
    for p in patterns:
        m = p.search(text)
        if m:
            return f"{label}: {m.group(0)}"
    return None


def evaluate(title: str, body: str, region: str | None) -> tuple[bool, str | None]:
    """Apply the region-appropriate hard filter.

    ``title`` and ``body`` are passed separately because some filters (SF)
    look only at the title per the spec.
    """
    if not region:
        return False, None
    full_text = title or ""
    if body:
        full_text = f"{title}\n{body}" if title else body

    if region.startswith("books"):
        # SF sub-category: cyberpunk / space-opera judged on title only.
        if region == "books:SF":
            r = _fire("books:SF hard filter (title)", _BOOKS_SF_TITLE_ONLY, title)
            if r:
                return True, r
        # Romance / light novel: all books regions, title + body.
        r = _fire("books hard filter (romance/LN)", _BOOKS_ROMANCE, full_text)
        if r:
            return True, r
        return False, None

    if region == "companies:Cocolomi":
        r = _fire(
            "companies:Cocolomi hard filter (competitor)",
            _COCOLOMI_COMPETITORS,
            full_text,
        )
        if r:
            return True, r
        return False, None

    if region == "companies:Human Energy":
        r = _fire(
            "companies:Human Energy hard filter (competitor)",
            _HUMAN_ENERGY_COMPETITORS,
            full_text,
        )
        if r:
            return True, r
        return False, None

    if region == "outdoor":
        r = _fire(
            "outdoor hard filter (hardcore mountaineering)",
            _OUTDOOR_HARDCORE,
            full_text,
        )
        if r:
            return True, r
        return False, None

    return False, None
