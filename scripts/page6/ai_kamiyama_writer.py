"""第6面 AI神山コラム生成。

Strategy:
1. ``lib.miibo.reset_short_term_memory()`` — yesterday's context をクリア
2. ``AI_KAMIYAMA_PROMPT_TEMPLATE`` に記事メタを差し込んで utterance 構築
3. ``lib.miibo.call_ai_kamiyama()`` で投入、応答取得
4. 応答を JSON parse → ``column_title`` + ``column_body`` を抽出
5. 失敗時 fallback 3 段階：
   * API 接続失敗 → 休載 placeholder（is_fallback=True）
   * JSON parse 失敗 → 生応答を column_body に、column_title は固定文
     （応答自体は得られている = 休載扱いではない、is_fallback=False）
   * 生応答も空 → 休載 placeholder

Anthropic API での代替コラム生成は **行わない**（AI神山の声を真似ない設計）。
"""

from __future__ import annotations

import json
import re
import sys

from ..lib import miibo
from .prompts import (
    AI_KAMIYAMA_PROMPT_TEMPLATE,
    FALLBACK_BODY,
    FALLBACK_TITLE,
)

_FENCE_RE = re.compile(
    r"^\s*```(?:json)?\s*\n?|\n?```\s*$", re.IGNORECASE | re.MULTILINE
)


def _build_utterance(article: dict) -> str:
    title = (article.get("title") or "").strip()
    source = (article.get("source_name") or "").strip()
    description = (article.get("description") or "").strip()
    return AI_KAMIYAMA_PROMPT_TEMPLATE.format(
        title=title, source=source, description=description,
    )


def _parse_json_response(raw_text: str) -> dict | None:
    """Extract column_title + column_body from raw response text.

    Returns the parsed dict on success, None on parse failure.
    """
    if not raw_text:
        return None
    text = _FENCE_RE.sub("", raw_text).strip()
    if not text.startswith("{"):
        idx = text.find("{")
        if idx < 0:
            return None
        text = text[idx:]
    end = text.rfind("}")
    if end >= 0:
        text = text[: end + 1]
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    title = parsed.get("column_title")
    body = parsed.get("column_body")
    if not isinstance(title, str) or not title.strip():
        return None
    if not isinstance(body, str) or not body.strip():
        return None
    return {"column_title": title.strip(), "column_body": body.strip()}


def write_column(
    article: dict,
    *,
    skip_reset: bool = False,
) -> dict:
    """Generate AI 神山's column for today's serendipity article.

    Returns::

        {
            "column_title": str,    # AI神山が生成 / fallback / "本日の一筆"
            "column_body": str,
            "is_fallback": bool,    # True iff API connection failed entirely
            "raw_response": dict | None,  # debug
            "elapsed_ms": int,      # 0 on fallback
            "ai_kamiyama_called": bool,
            "ai_kamiyama_failed": bool,
            "fallback_used": bool,
        }

    Three failure modes (per spec):
    * miibo API 接続失敗 → ``is_fallback=True``、固定文
    * JSON parse 失敗 → 生応答を ``column_body`` に、``column_title="本日の一筆"``、
      ``is_fallback=False``（応答自体は得られている）
    * 生応答も空 → ``is_fallback=True``
    """
    # 1) Reset short-term memory unless explicitly skipped (tests).
    if not skip_reset:
        try:
            miibo.reset_short_term_memory()
        except Exception as e:
            # reset_short_term_memory は内部で握り潰すが、保険として外側でも
            print(
                f"[page6/ai_kamiyama] reset failed (non-fatal): "
                f"{type(e).__name__}",
                file=sys.stderr,
            )

    # 2) Build utterance + 3) call API
    utterance = _build_utterance(article)
    try:
        response = miibo.call_ai_kamiyama(utterance)
    except miibo.MiiboAPIError as e:
        print(
            f"[page6/ai_kamiyama] miibo API failed: {e}, using fallback",
            file=sys.stderr,
        )
        return {
            "column_title": FALLBACK_TITLE,
            "column_body": FALLBACK_BODY,
            "is_fallback": True,
            "raw_response": None,
            "elapsed_ms": 0,
            "ai_kamiyama_called": True,
            "ai_kamiyama_failed": True,
            "fallback_used": True,
        }

    raw = response.utterance_response
    elapsed = response.elapsed_ms

    # 4) Parse JSON
    parsed = _parse_json_response(raw)
    if parsed is not None:
        return {
            "column_title": parsed["column_title"],
            "column_body": parsed["column_body"],
            "is_fallback": False,
            "raw_response": response.raw_response,
            "elapsed_ms": elapsed,
            "ai_kamiyama_called": True,
            "ai_kamiyama_failed": False,
            "fallback_used": False,
        }

    # JSON parse failed but we have raw text — use it directly per spec.
    if raw and raw.strip():
        print(
            f"[page6/ai_kamiyama] WARN: JSON parse failed, using raw response "
            f"as column_body ({len(raw)} chars)",
            file=sys.stderr,
        )
        return {
            "column_title": "本日の一筆",
            "column_body": raw.strip(),
            "is_fallback": False,
            "raw_response": response.raw_response,
            "elapsed_ms": elapsed,
            "ai_kamiyama_called": True,
            "ai_kamiyama_failed": False,
            "fallback_used": False,
        }

    # Empty response — true休載
    print(
        "[page6/ai_kamiyama] WARN: empty response, using fallback",
        file=sys.stderr,
    )
    return {
        "column_title": FALLBACK_TITLE,
        "column_body": FALLBACK_BODY,
        "is_fallback": True,
        "raw_response": response.raw_response,
        "elapsed_ms": elapsed,
        "ai_kamiyama_called": True,
        "ai_kamiyama_failed": True,
        "fallback_used": True,
    }
