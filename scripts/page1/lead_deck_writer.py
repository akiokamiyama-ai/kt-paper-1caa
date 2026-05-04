"""LLM-generated lead deck for the Page I top article.

Sprint 5 task #3 (2026-05-04). The deck (リード文) replaces the previous
duplicate display where ``deck`` and ``dropcap`` both showed the same
``desc_ja`` string. New design:

  - deck    = LLM-generated lead in 60–100 chars (this module)
  - dropcap = desc_ja (article body excerpt, unchanged)

Voice differentiation:
  - Tribune editorial postscript / lead deck: 媒体としての無人称、観察的
  - AIかみやま (Page V): 一人称、聞き上手、哲学的

Fallback (4-stage, mirrors editorial_writer):
  1. API exception → desc_ja[:80]
  2. JSON parse failure → desc_ja[:80]
  3. Length out of [30, 150] → desc_ja[:80]
  4. Empty deck → desc_ja[:80]

When desc_ja is also empty, fallback returns "" so the renderer skips the
``<p class="deck">`` element entirely (no empty deck on the page).
"""

from __future__ import annotations

import json
import re
import sys
import time
from typing import Any

from ..lib import llm

DEFAULT_MAX_TOKENS = 300

# Body length bounds for deck validation. Outside this band → fallback.
MIN_DECK_CHARS = 30
MAX_DECK_CHARS = 150

FALLBACK_TRUNCATE_CHARS = 80

# Banned phrases to enforce voice differentiation from AIかみやま. Mirrors
# the editorial postscript guard.
BANNED_PHRASES: tuple[str, ...] = (
    "聞き上手",
    "ディープリスニング",
    "環世界",
    "黒子",
    "自分は",
    "思います",
    "神山さん",
    "高尾山",
    "スナック",
)


SYSTEM_PROMPT = """あなたは Kamiyama Tribune の第1面トップ記事のリード文を書く編集者です。

【本紙の性格】
- 経営者・神山晃男（哲学・認知科学・経営に関心）のための朝刊
- 第1面トップは紙面の顔、英国紙の lead deck 風の格調

【リード文の役割】
- 記事の核心を 1〜2 文に圧縮
- 結論を先に出す、観察的、装飾を避ける
- 媒体としての無人称、または「本紙は」「今朝の」のような客観視
- 読者が dropcap（本文）に進む前に、記事の方向性を一文で掴める

【執筆方針】
- 60〜100 字
- 結論先出し、「なぜこの記事が重要か」を含意
- 個人的なエピソードや感情は出さない
- AIかみやま（聞き上手・哲学的）とは差別化、編集部の俯瞰視点
- 編集後記（紙面の最後）と voice を揃える：英国紙風、無人称、含み

禁止表現（AIかみやま との差別化）：
- 「聞き上手」「環世界」「黒子」
- 「自分は」「思います」のような一人称
- 「神山さん」のような個人名

推奨表現：
- 「本紙は」「今朝の」「世界の」
- 観察、対比、含み

【出力】
日本語タイトルがある場合は日本語で、原文タイトルが日本語の場合（日本語ソース）も日本語で。
60〜100 字のリード文を1〜2文で。

【出力フォーマット】
以下の JSON のみ出力。前置きや解説は不要。

{
  "deck": "60〜100字のリード文"
}
"""


def _build_user_message(article: dict) -> str:
    """Compose the user-side message: article context for the editor."""
    title_original = (article.get("title") or "").strip()
    title_ja = (article.get("title_ja") or "").strip()
    description = (article.get("description") or article.get("desc_ja") or "").strip()
    source_name = (article.get("source_name") or "外部ソース").strip()

    # If title_ja equals title (JA source), don't repeat
    title_ja_line = ""
    if title_ja and title_ja != title_original:
        title_ja_line = f"日本語タイトル：{title_ja}\n"

    return (
        f"原文タイトル：{title_original}\n"
        f"{title_ja_line}"
        f"記事本文（原文）：{description}\n"
        f"出典：{source_name}\n"
    )


def _coerce_deck(text: str) -> str:
    """Pull a JSON {"deck": "..."} payload out of the LLM response."""
    if not text:
        return ""
    s = text.strip()
    s = re.sub(r"^```(?:json)?\s*", "", s)
    s = re.sub(r"\s*```\s*$", "", s)
    try:
        obj = json.loads(s)
    except (json.JSONDecodeError, ValueError):
        return ""
    if not isinstance(obj, dict):
        return ""
    deck = obj.get("deck", "")
    if not isinstance(deck, str):
        return ""
    return deck.strip()


def _validate_deck(deck: str) -> tuple[bool, str]:
    """Return (is_ok, reason). reason is empty when is_ok=True."""
    if not deck:
        return False, "empty deck"
    n = len(deck)
    if n < MIN_DECK_CHARS:
        return False, f"too short ({n} chars < {MIN_DECK_CHARS})"
    if n > MAX_DECK_CHARS:
        return False, f"too long ({n} chars > {MAX_DECK_CHARS})"
    for phrase in BANNED_PHRASES:
        if phrase in deck:
            return False, f"banned phrase '{phrase}' (AIかみやま voice leakage)"
    return True, ""


def _truncate_fallback(article: dict, *, max_chars: int = FALLBACK_TRUNCATE_CHARS) -> str:
    """Simple truncate fallback when the LLM path fails or yields no deck.

    Prefers ``desc_ja`` over ``description`` so JA passthrough sources still
    show their original Japanese text rather than English. Returns ``""`` if
    both are empty (renderer omits the deck entirely).
    """
    text = (article.get("desc_ja") or "").strip()
    if not text:
        text = (article.get("description") or "").strip()
    if not text:
        return ""
    if len(text) <= max_chars:
        return text
    # Try to break at a sentence boundary near the limit
    cut = text[:max_chars]
    for sep in ("。", "．", ". ", "\n"):
        idx = cut.rfind(sep)
        if idx >= max_chars // 2:
            return cut[: idx + len(sep)].rstrip()
    return cut + "…"


def write_lead_deck(
    article: dict,
    *,
    model: str | None = None,
    max_tokens: int = DEFAULT_MAX_TOKENS,
) -> dict:
    """Generate the Page I top lead deck.

    Returns
    -------
    dict
        ``{"deck": str, "is_fallback": bool, "raw_response": dict,
        "elapsed_ms": int, "cost_usd": float}``
    """
    print("[lead_deck] generating...", file=sys.stderr)
    started = time.monotonic()
    user_msg = _build_user_message(article)

    raw_response: dict[str, Any] = {}
    try:
        response = llm.call_claude_with_retry(
            system=SYSTEM_PROMPT,
            user=user_msg,
            model=model or llm.DEFAULT_MODEL,
            max_tokens=max_tokens,
            cache_system=True,
        )
    except Exception as e:
        elapsed_ms = int((time.monotonic() - started) * 1000)
        reason = f"{type(e).__name__}: {llm.redact_key(str(e))[:160]}"
        print(f"[lead_deck] FALLBACK (api_error: {reason})", file=sys.stderr)
        return {
            "deck": _truncate_fallback(article),
            "is_fallback": True,
            "raw_response": {},
            "elapsed_ms": elapsed_ms,
            "cost_usd": 0.0,
            "fallback_reason": reason,
        }

    elapsed_ms = int((time.monotonic() - started) * 1000)
    raw_text = response.text or ""
    raw_response = {
        "model": response.model,
        "input_tokens": response.input_tokens,
        "output_tokens": response.output_tokens,
        "cost_usd": response.cost_usd,
        "stop_reason": response.stop_reason,
        "text": raw_text,
    }

    deck = _coerce_deck(raw_text)
    is_ok, reason = _validate_deck(deck)
    if not is_ok:
        print(
            f"[lead_deck] FALLBACK ({reason}); raw[:80]={raw_text[:80]!r}",
            file=sys.stderr,
        )
        return {
            "deck": _truncate_fallback(article),
            "is_fallback": True,
            "raw_response": raw_response,
            "elapsed_ms": elapsed_ms,
            "cost_usd": response.cost_usd,
            "fallback_reason": reason,
        }

    print(
        f"[lead_deck] OK ({elapsed_ms}ms, ${response.cost_usd:.4f}), "
        f"output[:30]={deck[:30]!r}",
        file=sys.stderr,
    )
    return {
        "deck": deck,
        "is_fallback": False,
        "raw_response": raw_response,
        "elapsed_ms": elapsed_ms,
        "cost_usd": response.cost_usd,
    }
