"""Translation helpers shared between page builders.

C81 段階 4 (Sprint 9, 2026-06-13, Fable review M6 god module 分割): 旧
``regen_front_page_v2.py`` から翻訳判定 / 翻訳経路を切り出した。

提供する API
============

- ``JAPANESE_SOURCE_PATTERNS``: EN 名で書かれた JA media（"Forbes Japan" 等）の
  パターン
- ``TRANSLATE_DELAY``: per-call sleep（外部 API rate limit 保護）
- ``is_japanese_source(name)``: name から JA 判定（heuristic、name の文字種
  比率 + パターンマッチ）
- ``is_japanese_article(article)``: Article.source_language を最優先、
  欠落時は name heuristic に fallback
- ``translate_article(article)``: in-place で ``title_ja`` / ``desc_ja`` を埋める
- ``translate_for_render(articles)``: バッチ版（ログ + 各 article で
  ``translate_article`` を呼ぶ）

Sprint 5 ポリシー（2026-05-03）: タイトルのみ翻訳、description は原文
passthrough。Sprint 6+ ポストモーメント観察結果を踏まえて、本文翻訳を
復活させる場合は ``translate_article`` 内の docstring コメント参照。
"""

from __future__ import annotations

import re
import sys
import time

from .translate import translate


# EN 名で書かれているが内容は JA の media。translate を skip する allowlist。
JAPANESE_SOURCE_PATTERNS: tuple[str, ...] = (
    "Foresight",
    "Forbes Japan",
    "ZDNet Japan",
    "ITmedia",
    "PR TIMES",
)

# Per-translation API call の sleep（rate limit 保護）。
TRANSLATE_DELAY = 0.3


def is_japanese_source(source_name: str | None) -> bool:
    """Detect whether a source's content is Japanese (so translation is skipped).

    Uses two signals:
    1. Substring match against ``JAPANESE_SOURCE_PATTERNS`` (covers EN-named
       JA sources like "Forbes Japan", "ZDNet Japan", "ITmedia AI＋").
    2. Heuristic: source name contains ≥2 hiragana / katakana / kanji
       characters (covers "経済産業省ニュースリリース", "日本の人事部 プロネット",
       "ビジネスチャンス", "DIAMONDハーバード・ビジネス・レビュー", etc.).

    EN-only sources (HBR.org, MIT Sloan, Aeon, BBC, Economist) match neither
    and fall through to translation.
    """
    if not source_name:
        return False
    if any(pat in source_name for pat in JAPANESE_SOURCE_PATTERNS):
        return True
    # Strip parenthetical metadata like "Foresight（新潮社）" or
    # "Harvard Business Review（HBR.org）" — these annotations contain JA chars
    # but the actual content language is determined by the rest of the name.
    name_stripped = re.sub(r"[（(][^）)]*[）)]", "", source_name)
    ja_chars = sum(
        1 for c in name_stripped
        if "぀" <= c <= "ゟ"   # hiragana
        or "゠" <= c <= "ヿ"   # katakana
        or "一" <= c <= "鿿"   # kanji
    )
    return ja_chars >= 2


def is_japanese_article(article: dict) -> bool:
    """記事の言語判定。primary signal は Article.source_language（Sprint 5、
    sources/*.md の language: ja|en に基づき drivers から伝播）。

    source_language キーが存在しない場合（page2 経路など、まだ伝播路が
    通っていない経路の article dict 等）は ``is_japanese_source`` heuristic に
    フォールバックする。RSS 仕様変更や source 未タグ漏れの保険も兼ねる。
    """
    sl = article.get("source_language")
    if sl == "en":
        return False
    if sl == "ja":
        return True
    return is_japanese_source(article.get("source_name", ""))


def translate_article(article: dict) -> None:
    """Populate ``title_ja`` / ``desc_ja`` in-place.

    翻訳ポリシー Sprint 5 で「タイトルのみ翻訳」に変更（2026-05-03）。
    本文（description）は原文のまま desc_ja に代入する。

    本文翻訳を復活させる場合：
      1. ↓ ブロックコメントを解除（下の `# desc_ja = translate(desc)` 等）
      2. その下の `desc_ja = desc  # passthrough (Sprint 5)` 行を削除
      3. ``translate_for_render`` のログメッセージ "(title only)" を戻す
      4. テスト ``test_translate_*_passthrough_desc`` を更新
    """
    if is_japanese_article(article):
        article["title_ja"] = article.get("title", "")
        article["desc_ja"] = article.get("description", "")
        return
    title = article.get("title", "") or ""
    desc = article.get("description", "") or ""
    title_ja = translate(title) if title else ""
    time.sleep(TRANSLATE_DELAY)
    # --- Sprint 5 (2026-05-03): 本文翻訳を停止、原文 passthrough ---
    # desc_ja = translate(desc) if desc else ""
    # time.sleep(TRANSLATE_DELAY)
    desc_ja = desc  # passthrough (Sprint 5)
    # --- end Sprint 5 ---
    article["title_ja"] = title_ja or title
    article["desc_ja"] = desc_ja or desc


def translate_for_render(articles: list[dict]) -> None:
    """Add title_ja (translated) and desc_ja (= description passthrough) to each article.

    Sprint 5 (2026-05-03): タイトルのみ翻訳、本文は原文 passthrough。
    """
    for i, a in enumerate(articles):
        is_ja = is_japanese_article(a)
        if is_ja:
            marker = " (JA passthrough)"
        else:
            marker = " (title only)"
        print(
            f"  [{i+1}] translating: {a.get('title', '')[:60]}{marker}",
            file=sys.stderr,
        )
        translate_article(a)
