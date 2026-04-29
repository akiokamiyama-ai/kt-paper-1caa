"""Anthropic API key handling and call dispatch.

Two responsibilities:

1. **API key validator** — read ``ANTHROPIC_API_KEY`` from the environment,
   refuse to proceed if missing or malformed. Never accept the key from a
   config file, command-line argument, or commit.

2. **call_claude()** — Phase 2 entry point used by Stage 2 (LLM batch
   evaluation). Wraps the Anthropic SDK with three guarantees:
   * Daily cost/call cap is enforced via ``llm_usage.check_caps``.
   * Token usage (including prompt-cache breakdown) is recorded via
     ``llm_usage.record_call``.
   * Prompt caching is on by default for the system prompt — Stage 2 sends
     the same ~1,800-token system prompt across many batches, and the 5-min
     ephemeral cache turns most calls into cache reads at ~10× lower input
     cost (see docs/aesthetics_design_v1.md §4.2 and
     docs/stage2_prompts_v1.md §8).

See docs/security_review_v1.md §6 for the threat model this module addresses.
"""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass

from . import llm_usage

ANTHROPIC_API_KEY_ENV = "ANTHROPIC_API_KEY"
DEFAULT_MODEL = "claude-sonnet-4-6"
EXPECTED_KEY_PREFIX = "sk-ant-"

# Default response-token budget large enough for a 10-article Stage 2 batch
# (about 3,300 tokens of JSON output per docs/stage2_prompts_v1.md §8.1) with
# headroom for verbose reasons.
DEFAULT_MAX_TOKENS = 4096

# Pattern for redacting any leaked API key out of error / log strings.
_API_KEY_PATTERN = re.compile(r"sk-ant-[A-Za-z0-9_\-]+")


def get_api_key() -> str:
    """Read and validate the Anthropic API key from the environment.

    Raises RuntimeError with an actionable message if the key is missing
    or malformed.
    """
    key = os.environ.get(ANTHROPIC_API_KEY_ENV)
    if not key:
        raise RuntimeError(
            f"{ANTHROPIC_API_KEY_ENV} environment variable not set. "
            f"Set it in ~/.bashrc or ~/.profile (e.g. "
            f"`export {ANTHROPIC_API_KEY_ENV}=sk-ant-...`) and chmod 600 the "
            "file. Never commit the key. Never write it to "
            "config/site_overrides.toml or any tracked file."
        )
    if not key.startswith(EXPECTED_KEY_PREFIX):
        raise RuntimeError(
            f"{ANTHROPIC_API_KEY_ENV} does not look like an Anthropic key "
            f"(expected to start with {EXPECTED_KEY_PREFIX!r}). Refusing "
            "to use to avoid sending an unrelated secret over the network."
        )
    return key


def redact_key(text: str) -> str:
    """Replace any Anthropic API key-shaped substring with a placeholder.

    Used before writing error excerpts to logs or stderr — the SDK
    occasionally surfaces the key in raw HTTP error bodies.
    """
    if not text:
        return text
    return _API_KEY_PATTERN.sub("[REDACTED]", text)


@dataclass
class ClaudeResponse:
    """Plain dataclass return so callers don't take a hard dependency on the SDK."""

    text: str
    model: str
    input_tokens: int
    output_tokens: int
    cache_creation_tokens: int
    cache_read_tokens: int
    cost_usd: float
    stop_reason: str | None
    raw_id: str | None


class CapExceededError(RuntimeError):
    """Raised when the daily cost / call cap is reached before a call fires."""


def call_claude(
    *,
    system: str,
    user: str,
    model: str = DEFAULT_MODEL,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    cache_system: bool = True,
    temperature: float | None = None,
) -> ClaudeResponse:
    """Single-turn call to Claude with optional prompt caching on the system message.

    Parameters
    ----------
    system :
        System prompt text. When ``cache_system=True`` (default) it is wrapped
        in a single ``ephemeral`` cache_control block so Anthropic caches it
        for 5 minutes.
    user :
        User message body. Always sent fresh (not cached).
    model :
        Anthropic model id. Defaults to ``claude-sonnet-4-6`` (Stage 2).
    max_tokens :
        Output cap. Anthropic requires this to be set explicitly.
    cache_system :
        If False, sends the system prompt without ``cache_control``.
    temperature :
        Optional sampling temperature; SDK default if None.

    Returns
    -------
    ClaudeResponse
        ``text`` is the concatenated assistant text. Token counts and cost
        are populated from ``response.usage``.

    Raises
    ------
    CapExceededError
        If the daily cap was already reached before this call.
    Other exceptions from the Anthropic SDK propagate (callers handle retry).
    """
    # Lazy import: scripts/fetch.py and scripts/regen_front_page.py do not
    # need the SDK, and we don't want to make anthropic a hard import for
    # the whole codebase.
    import anthropic

    # 1) Cap check (second-line defense; first line is the Anthropic Console
    # monthly budget).
    cap = llm_usage.check_caps()
    if not cap.ok:
        raise CapExceededError(
            f"daily LLM cap reached ({cap.reason}); "
            f"today {cap.today_calls} calls, ${cap.today_cost_usd:.4f}"
        )

    # 2) Build the system content. Use the list-of-blocks form when caching,
    # which is the only shape that accepts cache_control.
    if cache_system:
        system_arg: str | list = [
            {
                "type": "text",
                "text": system,
                "cache_control": {"type": "ephemeral"},
            }
        ]
    else:
        system_arg = system

    create_kwargs: dict = {
        "model": model,
        "max_tokens": max_tokens,
        "system": system_arg,
        "messages": [{"role": "user", "content": user}],
    }
    if temperature is not None:
        create_kwargs["temperature"] = temperature

    # 3) Call. The SDK reads ANTHROPIC_API_KEY itself, but we validate first
    # so the error path is consistent.
    get_api_key()
    client = anthropic.Anthropic()
    response = client.messages.create(**create_kwargs)

    # 4) Extract content text.
    text_parts: list[str] = []
    for block in response.content:
        if getattr(block, "type", None) == "text":
            text_parts.append(block.text)
    text = "".join(text_parts)

    # 5) Pull usage. Cache fields are present only when caching was used and
    # the model supports it; default to 0 otherwise.
    usage = response.usage
    input_tokens = int(getattr(usage, "input_tokens", 0) or 0)
    output_tokens = int(getattr(usage, "output_tokens", 0) or 0)
    cache_creation_tokens = int(
        getattr(usage, "cache_creation_input_tokens", 0) or 0
    )
    cache_read_tokens = int(getattr(usage, "cache_read_input_tokens", 0) or 0)

    # 6) Record usage so the daily totals stay current.
    llm_usage.record_call(
        model,
        input_tokens,
        output_tokens,
        cache_creation_tokens=cache_creation_tokens,
        cache_read_tokens=cache_read_tokens,
    )

    cost = llm_usage.estimate_cost(
        model,
        input_tokens,
        output_tokens,
        cache_creation_tokens=cache_creation_tokens,
        cache_read_tokens=cache_read_tokens,
    )

    return ClaudeResponse(
        text=text,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_creation_tokens=cache_creation_tokens,
        cache_read_tokens=cache_read_tokens,
        cost_usd=cost,
        stop_reason=getattr(response, "stop_reason", None),
        raw_id=getattr(response, "id", None),
    )


def call_claude_with_retry(
    *,
    system: str,
    user: str,
    model: str = DEFAULT_MODEL,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    cache_system: bool = True,
    max_attempts: int = 3,
) -> ClaudeResponse:
    """Wrap call_claude with exponential backoff for transient API errors.

    Backoff schedule per docs/stage2_prompts_v1.md §6: 1s, 2s, 4s.
    Caller-side retries (JSON parse, array length) are handled by Stage 2
    by re-invoking call_claude_with_retry with an adjusted user message.
    """
    import anthropic

    last_exc: Exception | None = None
    for attempt in range(max_attempts):
        try:
            return call_claude(
                system=system,
                user=user,
                model=model,
                max_tokens=max_tokens,
                cache_system=cache_system,
            )
        except CapExceededError:
            # The cap is a hard wall — no point retrying.
            raise
        except (
            anthropic.APITimeoutError,
            anthropic.RateLimitError,
            anthropic.APIConnectionError,
            anthropic.InternalServerError,
        ) as e:
            last_exc = e
            if attempt == max_attempts - 1:
                break
            time.sleep(2**attempt)
    # All attempts exhausted.
    msg = redact_key(str(last_exc) if last_exc else "unknown")
    raise RuntimeError(
        f"Anthropic API failed after {max_attempts} attempts: {msg}"
    ) from last_exc
