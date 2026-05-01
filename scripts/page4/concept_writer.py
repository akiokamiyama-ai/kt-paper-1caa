"""Generate the 'Concept of the Week' essay via LLM.

Input: concept dict (from concepts.yaml).
Output: ``{"concept": ..., "essay": ..., "is_fallback": bool, "cost_usd": float}``.

LLM failure or empty response → static fallback to the seed text. Sidebar-style
WARN logged so the issue is visible without crashing the page.
"""

from __future__ import annotations

import sys

from ..lib import llm

DEFAULT_MODEL = llm.DEFAULT_MODEL
DEFAULT_MAX_TOKENS = 1500
DEFAULT_TEMPERATURE = 0.7

SYSTEM_PROMPT = """あなたは Kamiyama Tribune 第4面 Arts & Letters の
『今週の概念』コラム執筆者です。

読者：哲学・認知科学・思想史に深い関心を持つ経営者。
専門用語は使ってよいが、初出時は短い補足を添える。
学術論文ではなく、知的な読み物として書く。
1段落で 400〜600字。前置きや結論を別段落にしない、
連続した思考の流れとして書く。"""


def _build_user_message(concept: dict) -> str:
    thinkers = ", ".join(concept.get("thinkers", []))
    seed = (concept.get("seed") or "").strip()
    return (
        "以下の概念について、コラム1本分（400〜600字）で書いてください。\n"
        "\n"
        f"概念名：{concept['name_ja']}（{concept['name_en']}）\n"
        f"領域：{concept['domain']}\n"
        f"代表的思想家：{thinkers}\n"
        f"基本定義：{seed}\n"
        "\n"
        "執筆方針：\n"
        "- 概念の核を最初の2〜3文で示す\n"
        "- 思想史的背景や代表思想家の文脈を1〜2文で\n"
        "- 現代の知的関心や日常感覚との接続を1〜2文で\n"
        "- 平易だが知的な水準を保つ\n"
        "- 神山氏（経営者、現象学・認知科学・暗黙知に関心）が\n"
        "  読んで思考を刺激される文章にする"
    )


def _static_fallback(concept: dict) -> str:
    """Return the seed text as-is for the fallback essay."""
    seed = (concept.get("seed") or "").strip()
    if not seed:
        return f"{concept.get('name_ja', '本日の概念')}に関する解説の生成に失敗しました。"
    return seed


def write_essay(
    concept: dict,
    *,
    model: str = DEFAULT_MODEL,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    temperature: float = DEFAULT_TEMPERATURE,
) -> dict:
    """Generate the essay. Returns a dict with concept/essay/is_fallback/cost_usd."""
    user_msg = _build_user_message(concept)

    try:
        response = llm.call_claude_with_retry(
            system=SYSTEM_PROMPT,
            user=user_msg,
            model=model,
            max_tokens=max_tokens,
            cache_system=True,
        )
        essay = (response.text or "").strip()
        cost = response.cost_usd
        if not essay:
            print(
                "[concept_writer] WARN: empty LLM response, using static fallback",
                file=sys.stderr,
            )
            return {
                "concept": concept,
                "essay": _static_fallback(concept),
                "is_fallback": True,
                "cost_usd": cost,
            }
        return {
            "concept": concept,
            "essay": essay,
            "is_fallback": False,
            "cost_usd": cost,
        }
    except Exception as e:
        print(
            f"[concept_writer] WARN: LLM failed ({type(e).__name__}: "
            f"{llm.redact_key(str(e))[:200]}), static fallback",
            file=sys.stderr,
        )
        return {
            "concept": concept,
            "essay": _static_fallback(concept),
            "is_fallback": True,
            "cost_usd": 0.0,
        }
