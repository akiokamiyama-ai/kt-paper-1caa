"""Anthropic API key handling and call dispatch.

This module locks in the secure pattern *before* Phase 2 introduces actual
LLM calls. Two responsibilities today:

1. **API key validator** — read ``ANTHROPIC_API_KEY`` from the environment,
   refuse to proceed if missing or malformed. Never accept the key from a
   config file, command-line argument, or commit.

2. **call_claude() stub** — the future entry point for selection-logic and
   editorial-comment LLM calls. Phase 2 will replace the NotImplementedError
   with an Anthropic SDK call. The stub exists now so callers can be
   wired up against a stable interface.

The actual LLM call is intentionally *not* implemented here yet — adding the
``anthropic`` SDK dependency is a Phase 2 decision, and the call signature
will firm up once docs/aesthetics_design_v1.md §4.2 (batch size 10, prompt
caching) is being implemented for real.

See docs/security_review_v1.md §6 for the threat model this module addresses.
"""

from __future__ import annotations

import os

ANTHROPIC_API_KEY_ENV = "ANTHROPIC_API_KEY"
DEFAULT_MODEL = "claude-sonnet-4-6"
EXPECTED_KEY_PREFIX = "sk-ant-"


def get_api_key() -> str:
    """Read and validate the Anthropic API key from the environment.

    Raises RuntimeError with an actionable message if the key is missing
    or malformed. Phase 2 callers should call this once at startup, not
    on every LLM call.
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


def call_claude(messages, *, model: str = DEFAULT_MODEL, **kwargs):
    """Phase 2 entry point. Not yet implemented.

    Once Phase 2 starts:

    1. ``pip install anthropic`` (record in pyproject / requirements when added).
    2. Replace the body below with an ``Anthropic(api_key=get_api_key())``
       client call.
    3. Wrap the call in :func:`scripts.lib.llm_usage.record_call` so the
       daily cost cap is enforced. Pattern::

           from .llm_usage import check_caps, record_call
           ok, reason = check_caps()
           if not ok:
               raise RuntimeError(f"LLM cap exceeded: {reason}")
           response = client.messages.create(...)
           record_call(model, response.usage.input_tokens, response.usage.output_tokens)
           return response

    4. Use prompt caching (``cache_control={"type": "ephemeral"}`` on the
       system message) per docs/aesthetics_design_v1.md §4.2.
    """
    raise NotImplementedError(
        "call_claude() is a Phase 2 entry point. See module docstring for the "
        "implementation pattern. Run scripts.lib.llm.get_api_key() in isolation "
        "to verify your environment before wiring this up."
    )
