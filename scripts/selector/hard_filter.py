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

# ---------------------------------------------------------------------------
# Podcast / audio content (universal hard filter, applies regardless of region)
#
# 動機：HBR IdeaCast 等の Podcast 記事は description に1行サマリしか含まれず、
# 本文（番組音声）は記事として読む形式に向かない。Tribune は紙面を読む
# 体験を前提とするため、音声番組へのリンクは hard exclude する。
# 検出は以下の3軸：URL パス（最強）、タイトル/本文の言及、media-type 接尾辞。
# Sprint 2 Step C で追加（2026-04-29）。
# ---------------------------------------------------------------------------

# URL に含まれていれば即除外する文字列パターン。
_PODCAST_URL_MARKERS: tuple[str, ...] = (
    "/podcast/",
    "/podcasts/",
    "podcast.fm",
    "anchor.fm",
    "spotify.com/episode",
    "apple.com/podcast",
    "podcasts.apple.com",
)

# タイトル/本文（description）に含まれていれば即除外する文字列パターン。
# 大文字小文字無視。日本語表記と英語表記の両方を含む。
_PODCAST_TEXT_MARKERS: tuple[str, ...] = (
    "podcast",
    "ポッドキャスト",
    "[audio]",
    "（音声）",
    "(音声)",
)


# ---------------------------------------------------------------------------
# Description length (universal hard filter, applies regardless of region)
#
# 動機：日経のように RSS feed が description を提供しない（または極端に
# 短い）ソースの記事は、紙面に並べたときに本文が空 / 半端で「未完成の
# 記事」が紙面に乗ってしまう。第3面で日経 Apple 記事の <p></p> 空 byline
# が表面化したため、Sprint 3 Step A の改善として universal フィルタを
# 追加（2026-05-01）。
# ---------------------------------------------------------------------------

DESCRIPTION_MIN_CHARS: int = 30


# Sprint 5 task #1 (2026-05-04): title-only feed の exempt 機能。
# config/site_overrides.toml の [sites."<host>"] に description_exempt=true を
# 設定したホストは description が空でも Stage 1 を通過する。朝日新聞デジタル
# 経済（www.asahi.com）が初の対象。日経（assets.wor.jp）は意図的に exempt
# しない（神山さん有料購読中、再露出価値が低いため現状の全弾きを維持）。
_SITE_CONFIG_CACHE = None


def _get_site_config():
    """Lazy-load and cache SiteConfig from config/site_overrides.toml."""
    global _SITE_CONFIG_CACHE
    if _SITE_CONFIG_CACHE is None:
        from ..lib.config_loader import load_site_config
        _SITE_CONFIG_CACHE = load_site_config()
    return _SITE_CONFIG_CACHE


def _reset_site_config_cache_for_tests() -> None:
    """Allow tests to force a fresh load (after monkey-patching the path)."""
    global _SITE_CONFIG_CACHE
    _SITE_CONFIG_CACHE = None


def _is_description_exempt(url: str) -> bool:
    """Return True if the article's host is in the description_exempt list."""
    if not url:
        return False
    try:
        return bool(_get_site_config().for_url(url).get("description_exempt", False))
    except Exception:
        # Defensive: corrupt config_loader shouldn't break Stage 1
        return False


def evaluate_description_length(article: dict) -> tuple[bool, str | None]:
    """Universal hard filter: exclude articles with description < 30 chars.

    Returns ``(excluded, reason)``. Reason is the constant
    ``"description_too_short"`` for downstream log auditing.

    Threshold rationale: 30 文字は「ニュース1文」の最小単位。これより短い
    descripton は事実上の「タイトルの繰り返し」「未完成の RSS 抜粋」で、
    紙面の本文として機能しない。30 字以上あれば最低限の論点提示が可能と
    判断（運用 1〜2 週間で頻度を見て v1.1 で調整）。

    Sprint 5 task #1 (2026-05-04): site_overrides.toml で description_exempt=true
    の host は description=0 でも通過させる（title-only feed への対応）。
    """
    if _is_description_exempt(article.get("url") or ""):
        return False, None
    desc = article.get("description") or ""
    if len(desc.strip()) < DESCRIPTION_MIN_CHARS:
        return True, "description_too_short"
    return False, None


def evaluate_podcast(
    *,
    url: str | None,
    title: str | None,
    description: str | None = None,
) -> tuple[bool, str | None]:
    """Universal hard filter: exclude podcast / audio-content articles.

    Returns ``(excluded, reason)``. The reason string is the constant
    ``"podcast_or_audio_content"`` per Sprint 2 Step C spec.

    This filter runs regardless of Source.category / region — Podcast
    articles can appear in any face of the paper, but the reading
    experience does not match a text-first morning paper.
    """
    # URL 検査（最強の signal）
    if url:
        url_lower = url.lower()
        for marker in _PODCAST_URL_MARKERS:
            if marker in url_lower:
                return True, "podcast_or_audio_content"

    # タイトル/本文の言及
    haystack_lower = " ".join(
        (title or "", description or "")
    ).lower()
    for marker in _PODCAST_TEXT_MARKERS:
        if marker.lower() in haystack_lower:
            return True, "podcast_or_audio_content"

    return False, None


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
