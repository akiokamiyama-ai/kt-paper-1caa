"""土曜 AI かみやま応答生成（Phase 3, 2026-05-23）.

2 段階構成（仕様 Q2 神山さん判断）：
  1. **Claude Haiku** で 1 週間のコメントを 200-400 字に編集（事務的）
  2. **miibo**（既存 AIかみやま agent 土曜 variant）で 600-1000 字の応答生成

各段で fallback：
  - コメント 0 件 → 軽量 fallback（両 LLM 呼ばず）
  - Haiku 失敗 → 原文 concat で digest 代用、miibo に進む
  - miibo 失敗 → SaturdayResult.is_fallback=True、紙面に「応答休載」placeholder
  - miibo JSON parse 失敗 → 生応答を response_body に、title は固定文

caller はテスト用に注入可能。
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from typing import Any, Callable

from .comments_reader import DailyComment
from .essay_generator import _angle_label_text  # 流用：曜日ラベル整形
from .monthly_pivotal import WeekContext
from .prompts import (
    SATURDAY_DIGEST_SYSTEM_PROMPT,
    SATURDAY_DIGEST_USER_TEMPLATE,
    SATURDAY_RESPONSE_UTTERANCE_TEMPLATE,
)

DIGEST_MODEL = "claude-haiku-4-5"
DIGEST_TAG = "page1_v3.saturday_digest"
DIGEST_MAX_TOKENS = 1024

_FENCE_RE = re.compile(
    r"^\s*```(?:json)?\s*\n?|\n?```\s*$", re.IGNORECASE | re.MULTILINE
)


# ----------------------------------------------------------------------------
# Result dataclass
# ----------------------------------------------------------------------------


@dataclass
class SaturdayResult:
    angle_label: str          # 階層 1: "土曜 - 応答"
    daily_question: str       # 階層 2: AIかみやま が付ける一文（任意、空可）
    response_title: str       # 階層 3: 応答タイトル
    comments_digest: str      # Haiku 抜粋（or 原文 fallback）200-400 字
    response_body: str        # miibo 応答 600-1000 字（or 失敗 placeholder）
    digest_cost_usd: float = 0.0
    is_fallback: bool = False  # True なら紙面に「応答休載」体裁
    digest_used_fallback: bool = False  # Haiku 失敗で原文 concat 使用


# ----------------------------------------------------------------------------
# Empty / fallback helpers
# ----------------------------------------------------------------------------


def _empty_comments_result(week: WeekContext) -> SaturdayResult:
    """コメント 0 件 → 軽量 fallback（仕様 §4.8.3）.

    LLM を一切呼ばない。来週予告セクションを厚めに見せる側で吸収する。
    """
    return SaturdayResult(
        angle_label=_angle_label_text(week),
        daily_question="",
        response_title="今週は神山さんのコメントなし",
        comments_digest="",
        response_body=(
            "今週は神山さんからのコメントがありませんでした。\n\n"
            "来週も Kamiyama Tribune は同じ主軸記事を異なる角度から読み解いていきます。"
            "お気軽にコメントをお寄せください。"
        ),
        digest_cost_usd=0.0,
        is_fallback=False,
    )


def _miibo_failure_result(
    week: WeekContext, digest: str, digest_cost: float, digest_fallback: bool, reason: str,
) -> SaturdayResult:
    """miibo 呼び出し失敗 → 応答休載 placeholder."""
    print(f"[page1_v3] saturday miibo failed ({reason}), using fallback", file=sys.stderr)
    return SaturdayResult(
        angle_label=_angle_label_text(week),
        daily_question="",
        response_title="AIかみやま応答休載",
        comments_digest=digest,
        response_body=(
            "本日は AIかみやま との通信または生成の失敗により応答を休載とします。\n\n"
            "1 週間のコメントは上記に収録しております。来週へお持ち越しください。"
        ),
        digest_cost_usd=digest_cost,
        is_fallback=True,
        digest_used_fallback=digest_fallback,
    )


def _raw_concat_digest(comments: list[DailyComment]) -> str:
    """Haiku 失敗時の素朴な digest（編集なしの原文 concat）."""
    lines = []
    for c in comments:
        head = f"【{c.target_date.isoformat()} ({c.day_label}・{c.angle_label_jp})】"
        body = c.body.strip().replace("\n\n", "\n")
        lines.append(f"{head}\n{body}")
    return "\n\n".join(lines)


# ----------------------------------------------------------------------------
# Haiku digest
# ----------------------------------------------------------------------------


def _format_angles_summary(past_essays: list[dict]) -> str:
    if not past_essays:
        return "（角度情報なし）"
    return "\n".join(
        f"- {e.get('date','?')} ({e.get('angle_label_jp','?')}): "
        f"{(e.get('essay') or {}).get('daily_question','')}"
        for e in past_essays
    )


def _format_comments_block(comments: list[DailyComment]) -> str:
    return "\n\n".join(
        f"[{c.target_date.isoformat()} ({c.day_label}・{c.angle_label_jp})]\n{c.body}"
        for c in comments
    )


def _default_haiku_caller(*, system: str, user: str) -> Any:
    from ..lib.llm import call_claude_with_retry
    return call_claude_with_retry(
        system=system, user=user,
        model=DIGEST_MODEL, max_tokens=DIGEST_MAX_TOKENS, tag=DIGEST_TAG,
    )


def _run_haiku_digest(
    week: WeekContext,
    past_essays: list[dict],
    comments: list[DailyComment],
    caller: Callable | None,
) -> tuple[str, float, bool]:
    """Returns (digest_text, cost_usd, used_fallback)."""
    invoke = caller or _default_haiku_caller
    user = SATURDAY_DIGEST_USER_TEMPLATE.format(
        title=week.article.get("title", ""),
        source=week.article.get("source", ""),
        angles_summary=_format_angles_summary(past_essays),
        comments_block=_format_comments_block(comments),
    )
    try:
        resp = invoke(system=SATURDAY_DIGEST_SYSTEM_PROMPT, user=user)
    except Exception as e:  # noqa: BLE001
        print(f"[page1_v3] saturday digest (Haiku) failed ({type(e).__name__}), "
              f"using raw concat", file=sys.stderr)
        return _raw_concat_digest(comments), 0.0, True
    text = (getattr(resp, "text", "") or "").strip()
    cost = float(getattr(resp, "cost_usd", 0.0) or 0.0)
    if not text:
        print("[page1_v3] saturday digest (Haiku) returned empty, using raw concat",
              file=sys.stderr)
        return _raw_concat_digest(comments), cost, True
    return text, cost, False


# ----------------------------------------------------------------------------
# miibo response
# ----------------------------------------------------------------------------


def _format_daily_questions(past_essays: list[dict]) -> str:
    if not past_essays:
        return "（過去日問いなし）"
    lines: list[str] = []
    for e in past_essays:
        d = e.get("date", "?")
        label = e.get("angle_label_jp", "?")
        q = (e.get("essay") or {}).get("daily_question", "")
        lines.append(f"- {d} ({label}): {q}")
    return "\n".join(lines)


def _default_miibo_caller(*, utterance: str) -> Any:
    from ..lib import miibo
    return miibo.call_ai_kamiyama(utterance)


def _parse_miibo_json(raw: str) -> dict | None:
    if not raw:
        return None
    text = _FENCE_RE.sub("", raw).strip()
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
    body = parsed.get("response_body")
    if not isinstance(body, str) or not body.strip():
        return None
    title = parsed.get("response_title") or "AIかみやま応答"
    question = parsed.get("daily_question") or ""
    return {
        "response_title": str(title).strip(),
        "response_body": body.strip(),
        "daily_question": str(question).strip(),
    }


# ----------------------------------------------------------------------------
# Public API
# ----------------------------------------------------------------------------


def generate_saturday_response(
    week: WeekContext,
    past_essays: list[dict],
    comments: list[DailyComment],
    *,
    haiku_caller: Callable | None = None,
    miibo_caller: Callable | None = None,
) -> SaturdayResult:
    """土曜紙面の AIかみやま 応答セクションを生成する.

    Parameters
    ----------
    week : WeekContext
        土曜の WeekContext（angle_key='response'）。
    past_essays : list[dict]
        当週の月-金の論考（``history.load_week_essays`` の出力）。
    comments : list[DailyComment]
        日-金の神山さんコメント（``comments_reader.load_week_comments``）。
    haiku_caller, miibo_caller : Callable | None
        テスト用注入。haiku は ``(system, user) -> Response``、
        miibo は ``(utterance) -> MiiboResponse`` のシグネチャ。
    """
    if not comments:
        return _empty_comments_result(week)

    # Step 1: Haiku で digest
    digest, digest_cost, digest_fallback = _run_haiku_digest(
        week, past_essays, comments, haiku_caller,
    )

    # Step 2: miibo で応答
    invoke_miibo = miibo_caller or _default_miibo_caller
    utterance = SATURDAY_RESPONSE_UTTERANCE_TEMPLATE.format(
        title=week.article.get("title", ""),
        source=week.article.get("source", ""),
        daily_questions_block=_format_daily_questions(past_essays),
        comments_digest=digest,
    )
    try:
        miibo_resp = invoke_miibo(utterance=utterance)
    except Exception as e:  # noqa: BLE001
        return _miibo_failure_result(
            week, digest, digest_cost, digest_fallback,
            f"miibo exception {type(e).__name__}",
        )
    raw = getattr(miibo_resp, "utterance_response", "") or ""
    parsed = _parse_miibo_json(raw)
    if parsed is None:
        # JSON parse 失敗だが生応答はある → 既存 AIかみやま と同じ救済策で
        # 生テキストを response_body に、title 固定。
        if raw and raw.strip():
            print("[page1_v3] saturday miibo JSON parse failed, using raw text",
                  file=sys.stderr)
            return SaturdayResult(
                angle_label=_angle_label_text(week),
                daily_question="",
                response_title="本日の応答",
                comments_digest=digest,
                response_body=raw.strip(),
                digest_cost_usd=digest_cost,
                is_fallback=False,
                digest_used_fallback=digest_fallback,
            )
        return _miibo_failure_result(
            week, digest, digest_cost, digest_fallback, "miibo empty response",
        )
    return SaturdayResult(
        angle_label=_angle_label_text(week),
        daily_question=parsed["daily_question"],
        response_title=parsed["response_title"],
        comments_digest=digest,
        response_body=parsed["response_body"],
        digest_cost_usd=digest_cost,
        is_fallback=False,
        digest_used_fallback=digest_fallback,
    )
