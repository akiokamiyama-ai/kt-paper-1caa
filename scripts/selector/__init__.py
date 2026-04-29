"""Stage 1 mechanical filters for Phase 2 article selection.

The selector applies three mechanical evaluators before the LLM-driven
Stage 2 sees an article:

* mainstream tag → 美意識2 score (+5/+3/0)
* keyword blacklist → 美意識4 penalty (0/-3/-5)
* region-aware hard filter (news_profile.md §5.2)

Public entry point: ``run_stage1(articles)`` in ``scripts.selector.stage1``.

The CLI in ``scripts.selector.cli`` exists for smoke-testing Stage 1 in
isolation; it does not write to archive/ or touch the live front page
pipeline.
"""

from .stage1 import run_stage1

__all__ = ["run_stage1"]
