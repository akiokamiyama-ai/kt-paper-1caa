"""日-金論考生成（Phase 3, 2026-05-23）.

Sonnet 4.6 を 1 call 呼び出し、4 要素（論考本文 + 3 階層タイトル + 用語解説 +
主軸記事引用）を JSON で出力させる。失敗時は fallback EssayResult を返し、
紙面に「論考休載」相当の placeholder を出す。

LLM caller はテスト用に注入可能。デフォルトは
``scripts.lib.llm.call_claude_with_retry`` を Sonnet 4.6 で呼ぶ。
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Callable

from .monthly_pivotal import ANNOTATION_LABEL_BY_ANGLE, WeekContext
from .prompts import (
    ANGLE_INSTRUCTIONS,
    ESSAY_SYSTEM_PROMPT,
    ESSAY_USER_TEMPLATE,
    format_full_text_section,
)

ESSAY_MODEL = "claude-sonnet-4-6"
ESSAY_TAG = "page1_v3.essay"
ESSAY_MAX_TOKENS = 4096

# Sprint 8 C24 (2026-05-24, 5/24 朝刊 fallback 受け): JSON parse 失敗時の
# 1 回 retry + 失敗時 raw response 保存先。
DEFAULT_FALLBACK_RAW_DIR = (
    Path(__file__).resolve().parent.parent.parent / "logs"
)

_FENCE_RE = re.compile(
    r"^\s*```(?:json)?\s*\n?|\n?```\s*$", re.IGNORECASE | re.MULTILINE
)

# ----------------------------------------------------------------------------
# Result dataclass
# ----------------------------------------------------------------------------


@dataclass
class EssayResult:
    """日-金論考の 4 要素 + メタデータ."""
    angle_label: str        # 階層 1: "日曜 - 全体像"
    daily_question: str     # 階層 2: 日替わりの問い 20-30 字
    essay_title: str        # 階層 3: 論考タイトル 15-25 字
    body: str               # 論考本文（厳守 2000 字以下、目安 1200-2000 字）
    annotation_label: str   # 用語解説欄ラベル
    annotation_body: str    # 用語解説 100-200 字
    quote_excerpt: str      # 主軸記事引用 300-500 字
    cost_usd: float = 0.0
    is_fallback: bool = False


# ----------------------------------------------------------------------------
# Prompt building
# ----------------------------------------------------------------------------


def _format_points(points: list[Any] | None) -> str:
    if not points:
        return "（要点記載なし）"
    return "\n".join(f"- {str(p)}" for p in points if p)


def _format_past_essays(past_essays: list[dict] | None) -> str:
    """過去日論考を context として整形（dict のリスト：history.load_week_essays の出力形式）."""
    if not past_essays:
        return "（過去日論考なし — 今週の初日）"
    blocks: list[str] = []
    for entry in past_essays:
        d = entry.get("date", "?")
        label = entry.get("angle_label_jp", "?")
        essay = entry.get("essay") or {}
        title = essay.get("essay_title", "")
        question = essay.get("daily_question", "")
        body_excerpt = (essay.get("body") or "").strip().replace("\n\n", " ")
        if len(body_excerpt) > 300:
            body_excerpt = body_excerpt[:300] + "…"
        blocks.append(
            f"--- {d} ({label}) ---\n"
            f"問い: {question}\nタイトル: {title}\n論旨抜粋: {body_excerpt}"
        )
    return "\n\n".join(blocks)


def _build_user_message(
    week: WeekContext,
    target_date: date,
    past_essays: list[dict] | None,
) -> str:
    a = week.article
    return ESSAY_USER_TEMPLATE.format(
        title=a.get("title", ""),
        source=a.get("source", ""),
        author=a.get("author", ""),
        published=a.get("published", ""),
        url=a.get("url", ""),
        summary=a.get("summary", ""),
        points_bullet=_format_points(a.get("points")),
        key_quote=a.get("key_quote", ""),
        key_quote_ja=a.get("key_quote_ja", ""),
        # C126 (2026-07-05): monthly_pivotal.json の article に
        # ``full_text_excerpt`` フィールドがあれば原文抜粋を LLM に届ける。
        # 無い / 空なら空文字（既存 W entry 完全互換）。
        full_text_section=format_full_text_section(a.get("full_text_excerpt", "")),
        date_str=target_date.isoformat(),
        day_label=week.day_label,
        angle_label_jp=week.angle_label_jp,
        angle_key=week.angle_key,
        angle_instruction=ANGLE_INSTRUCTIONS.get(week.angle_key, ""),
        past_essays_block=_format_past_essays(past_essays),
    )


# ----------------------------------------------------------------------------
# JSON parsing
# ----------------------------------------------------------------------------


def _parse_essay_json(raw: str) -> dict | None:
    """LLM 応答テキストから dict を取り出す。失敗時 None."""
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
    required = ("daily_question", "essay_title", "body",
                "annotation_label", "annotation_body", "quote_excerpt")
    for k in required:
        v = parsed.get(k)
        if not isinstance(v, str) or not v.strip():
            return None
    return {k: parsed[k].strip() for k in required}


# ----------------------------------------------------------------------------
# Fallback
# ----------------------------------------------------------------------------


def _angle_label_text(week: WeekContext) -> str:
    """階層 1 のラベル（"日曜 - 全体像" 形式）.

    曜日（漢字 1 字）→ "日曜"/"月曜"/.../"土曜" に展開する。
    """
    day_full = {
        "日": "日曜", "月": "月曜", "火": "火曜", "水": "水曜",
        "木": "木曜", "金": "金曜", "土": "土曜",
    }.get(week.day_label, week.day_label)
    return f"{day_full} - {week.angle_label_jp}"


def _save_fallback_raw(target_date: date, raw: str, out_dir: Path) -> Path | None:
    """fallback 時の raw response を artifact 用ファイルに保存.

    GHA workflow が ``logs/page1_v3_fallback_raw_*.txt`` を audit-logs artifact
    に同梱できるようファイル名規約を統一する（C24, 2026-05-24）。
    """
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"page1_v3_fallback_raw_{target_date.isoformat()}.txt"
        path.write_text(raw or "(empty)", encoding="utf-8")
        return path
    except OSError as e:
        print(f"[page1_v3] failed to save fallback raw: {e}", file=sys.stderr)
        return None


def _make_fallback(
    week: WeekContext,
    target_date: date,
    reason: str,
    *,
    raw: str = "",
    out_dir: Path | None = None,
) -> EssayResult:
    """LLM 失敗時の placeholder。紙面は「論考休載」体裁で出す.

    ``raw`` が非空なら snippet を stderr + 全文を logs/ にダンプ（C24 観測強化）。
    """
    print(f"[page1_v3] essay LLM failed ({reason}), using fallback", file=sys.stderr)
    if raw:
        snippet = raw[:1000].replace("\n", " ").replace("\r", " ")
        print(
            f"[page1_v3] raw response snippet (first 1000 chars, newlines→space): "
            f"{snippet}",
            file=sys.stderr,
        )
        dump_dir = out_dir or DEFAULT_FALLBACK_RAW_DIR
        saved = _save_fallback_raw(target_date, raw, dump_dir)
        if saved:
            print(f"[page1_v3] full raw saved to {saved}", file=sys.stderr)
    return EssayResult(
        angle_label=_angle_label_text(week),
        daily_question="本日の論考は休載となります",
        essay_title="論考休載",
        body=(
            "本日の論考は通信または生成の失敗により休載となります。\n\n"
            "主軸記事『" + (week.article.get("title") or "") + "』は引き続き今週の"
            "テーマとして掲載しております。明日以降の論考にご期待ください。"
        ),
        annotation_label=ANNOTATION_LABEL_BY_ANGLE.get(week.angle_key, "用語解説"),
        annotation_body="本日は用語解説も休載となります。",
        quote_excerpt=(week.article.get("key_quote_ja") or week.article.get("key_quote") or ""),
        cost_usd=0.0,
        is_fallback=True,
    )


def _build_essay_result(
    week: WeekContext, parsed: dict, cost: float,
) -> EssayResult:
    """parse 成功時の EssayResult 構築（generate_essay の 2 経路で共有）."""
    return EssayResult(
        angle_label=_angle_label_text(week),
        daily_question=parsed["daily_question"],
        essay_title=parsed["essay_title"],
        body=parsed["body"],
        annotation_label=parsed["annotation_label"],
        annotation_body=parsed["annotation_body"],
        quote_excerpt=parsed["quote_excerpt"],
        cost_usd=cost,
        is_fallback=False,
    )


# ----------------------------------------------------------------------------
# Default LLM caller
# ----------------------------------------------------------------------------


def _default_llm_caller(*, system: str, user: str) -> Any:
    """call_claude_with_retry を Sonnet 4.6 で呼ぶ。tag = page1_v3.essay."""
    from ..lib.llm import call_claude_with_retry
    return call_claude_with_retry(
        system=system,
        user=user,
        model=ESSAY_MODEL,
        max_tokens=ESSAY_MAX_TOKENS,
        tag=ESSAY_TAG,
    )


# ----------------------------------------------------------------------------
# Public API
# ----------------------------------------------------------------------------


def generate_essay(
    week: WeekContext,
    target_date: date,
    *,
    past_essays: list[dict] | None = None,
    llm_caller: Callable | None = None,
    fallback_raw_dir: Path | None = None,
) -> EssayResult:
    """日-金論考を 1 本生成する.

    JSON parse 失敗時は **1 回だけ retry** する（C24 強化, 2026-05-24）。
    Sonnet 応答は非決定的なため、2 回目で成功する確率が実用的に高い。
    両 attempt とも失敗した場合のみ fallback。

    Parameters
    ----------
    week : WeekContext
        当該日の週文脈（主軸記事 + 角度を保持）。
    target_date : date
        対象日（YYYY-MM-DD）。
    past_essays : list[dict] | None
        当週の過去日論考（``history.load_week_essays`` の出力）。月-金で活用。
    llm_caller : Callable | None
        テスト用注入。``(system: str, user: str) -> Response`` のシグネチャ。
        Response は ``.text`` ``.cost_usd`` を持つことを期待する。
    fallback_raw_dir : Path | None
        fallback 時の raw response ダンプ先（テスト用）。default は
        ``logs/`` ディレクトリ。GHA artifact に同梱される。
    """
    caller = llm_caller or _default_llm_caller
    system = ESSAY_SYSTEM_PROMPT
    user = _build_user_message(week, target_date, past_essays)
    out_dir = fallback_raw_dir or DEFAULT_FALLBACK_RAW_DIR

    # ----- Attempt 1 -----
    try:
        resp = caller(system=system, user=user)
    except Exception as e:  # noqa: BLE001
        return _make_fallback(
            week, target_date, f"call exception {type(e).__name__}",
            out_dir=out_dir,
        )
    raw = getattr(resp, "text", "") or ""
    cost = float(getattr(resp, "cost_usd", 0.0) or 0.0)
    parsed = _parse_essay_json(raw)
    if parsed is not None:
        return _build_essay_result(week, parsed, cost)

    # ----- Attempt 2: JSON parse 失敗時の 1 回 retry -----
    print(
        f"[page1_v3] essay JSON parse failed on attempt 1 "
        f"(raw {len(raw)} chars), retrying once",
        file=sys.stderr,
    )
    try:
        resp2 = caller(system=system, user=user)
    except Exception as e:  # noqa: BLE001
        return _make_fallback(
            week, target_date,
            f"retry call exception {type(e).__name__}",
            raw=raw, out_dir=out_dir,
        )
    raw2 = getattr(resp2, "text", "") or ""
    cost2 = float(getattr(resp2, "cost_usd", 0.0) or 0.0)
    parsed2 = _parse_essay_json(raw2)
    if parsed2 is not None:
        print(
            f"[page1_v3] essay JSON parse succeeded on attempt 2 "
            f"(retry cost ${cost2:.4f}, total ${cost + cost2:.4f})",
            file=sys.stderr,
        )
        return _build_essay_result(week, parsed2, cost + cost2)

    # ----- 両方失敗: fallback + 両 attempt の raw を連結保存 -----
    combined = (
        f"=== attempt 1 ({len(raw)} chars) ===\n{raw}\n\n"
        f"=== attempt 2 ({len(raw2)} chars) ===\n{raw2}"
    )
    return _make_fallback(
        week, target_date, "JSON parse failed (both attempts)",
        raw=combined, out_dir=out_dir,
    )
