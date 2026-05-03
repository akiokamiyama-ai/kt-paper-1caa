"""Generate the Tribune editorial postscript via the Anthropic API.

Sprint 4 Phase 3 (2026-05-03). Uses scripts.lib.llm.call_claude_with_retry
which respects the daily LLM cost cap and the existing usage log.

Returns ``is_fallback=True`` (and an empty body) on any of:
  - API exception (CapExceededError, network, etc.)
  - JSON parse failure
  - Body length outside [MIN_BODY_CHARS, MAX_BODY_CHARS]
  - Empty body string
  - Body contains a banned phrase (AIかみやま voice leakage)

When fallback is signalled, the renderer omits the editorial footer entirely
(per design: silently degrade, paper ends at Page VI).
"""

from __future__ import annotations

import json
import re
import sys
import time
from typing import Any

from ..lib import llm
from .prompts import (
    BANNED_PHRASES,
    EDITORIAL_PROMPT_TEMPLATE,
    MAX_BODY_CHARS,
    MIN_BODY_CHARS,
)


DEFAULT_MAX_TOKENS = 500


def _coerce_body(text: str) -> str:
    """Pull a JSON {"body": "..."} payload out of the LLM response.

    Tolerates code fences (```json ... ```) since some prompts trigger them
    despite the instruction to omit fences.
    """
    if not text:
        return ""
    s = text.strip()
    # Strip code fences if present
    s = re.sub(r"^```(?:json)?\s*", "", s)
    s = re.sub(r"\s*```\s*$", "", s)
    try:
        obj = json.loads(s)
    except (json.JSONDecodeError, ValueError):
        return ""
    if not isinstance(obj, dict):
        return ""
    body = obj.get("body", "")
    if not isinstance(body, str):
        return ""
    return body.strip()


def _validate_body(body: str) -> tuple[bool, str]:
    """Return (is_ok, reason). reason is empty when is_ok=True."""
    if not body:
        return False, "empty body"
    n = len(body)
    if n < MIN_BODY_CHARS:
        return False, f"too short ({n} chars < {MIN_BODY_CHARS})"
    if n > MAX_BODY_CHARS:
        return False, f"too long ({n} chars > {MAX_BODY_CHARS})"
    for phrase in BANNED_PHRASES:
        if phrase in body:
            return False, f"banned phrase '{phrase}' (AIかみやま voice leakage)"
    return True, ""


def write_editorial(
    context: dict,
    *,
    model: str | None = None,
    max_tokens: int = DEFAULT_MAX_TOKENS,
) -> dict:
    """Generate the Tribune editorial postscript from per-page context.

    Returns
    -------
    dict
        ``{"body": str, "is_fallback": bool, "raw_response": dict,
        "elapsed_ms": int, "cost_usd": float}``
    """
    print("[editorial] generating...", file=sys.stderr)
    started = time.monotonic()
    context_json = json.dumps(context, ensure_ascii=False, indent=2)
    user_msg = EDITORIAL_PROMPT_TEMPLATE.format(context_json=context_json)

    raw_response: dict[str, Any] = {}
    try:
        response = llm.call_claude_with_retry(
            system="",  # all instructions are in the user prompt for this task
            user=user_msg,
            model=model or llm.DEFAULT_MODEL,
            max_tokens=max_tokens,
            cache_system=False,
        )
    except Exception as e:
        elapsed_ms = int((time.monotonic() - started) * 1000)
        reason = f"{type(e).__name__}: {llm.redact_key(str(e))[:160]}"
        print(f"[editorial] FALLBACK (api_error: {reason})", file=sys.stderr)
        return {
            "body": "",
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

    body = _coerce_body(raw_text)
    is_ok, reason = _validate_body(body)
    if not is_ok:
        print(
            f"[editorial] FALLBACK ({reason}); raw[:80]={raw_text[:80]!r}",
            file=sys.stderr,
        )
        return {
            "body": "",
            "is_fallback": True,
            "raw_response": raw_response,
            "elapsed_ms": elapsed_ms,
            "cost_usd": response.cost_usd,
            "fallback_reason": reason,
        }

    print(
        f"[editorial] OK ({elapsed_ms}ms, ${response.cost_usd:.4f}), "
        f"output[:30]={body[:30]!r}",
        file=sys.stderr,
    )
    return {
        "body": body,
        "is_fallback": False,
        "raw_response": raw_response,
        "elapsed_ms": elapsed_ms,
        "cost_usd": response.cost_usd,
    }
