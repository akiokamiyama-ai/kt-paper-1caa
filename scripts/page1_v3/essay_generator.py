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

# C172 (2026-08-19): 論考 JSON の必須キー。
REQUIRED_KEYS: tuple[str, ...] = (
    "daily_question", "essay_title", "body",
    "annotation_label", "annotation_body", "quote_excerpt",
)

# 欠落・破損しても**紙面を成立させられる**キー（部分救済の対象）。
#
# 8/19 (W13 Day 4, 水曜 thinker) に essay が 2 回とも parse に失敗して休載した。
# 応答は完結しており（output 2252 / 1969 tokens、上限 4096 に未達）、
# 論考本文そのものは書けていた可能性が高いのに、紙面全体を落としていた。
#
# ``quote_excerpt`` は「主軸記事から 300-500 字を**原文ママ**抜粋」という指示で、
# W13 の主軸記事（Byung-Chul Han、full_text_excerpt 27,201 字）は ASCII
# ダブルクォートを 88 個含む。"great death" / "guesthouse" / "Friendliness"
# のような術語がすべて引用符付きで、水曜 thinker の角度はまさにそこを取りに行く。
# 原文ママの引用を JSON 文字列値へ入れる時に \" を 1 つ落とせば構文が壊れる。
#
# 引用欄 1 つのために論考本文を捨てるのは割に合わないので、このキーだけは
# ``key_quote_ja`` で代替して紙面を成立させる。body 等は本文が無ければ紙面が
# 成立しないので救済しない。
RESCUABLE_KEYS: frozenset[str] = frozenset({"quote_excerpt"})

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


@dataclass
class EssayParse:
    """``_parse_essay_json`` の結果.

    C172 (2026-08-19): 旧実装は成功=dict / 失敗=None しか返さず、呼び出し側は
    構文破損もキー欠落も一律 ``"JSON parse failed"`` とログしていた。8/19 の
    休載時にどちらだったのか事後に判別できず、原因追求が止まった。
    """
    data: dict | None = None
    reason: str | None = None
    rescued: tuple[str, ...] = ()


def _classify_key(parsed: dict, key: str) -> str | None:
    """必須キー 1 つの状態を判定。問題なければ None."""
    if key not in parsed:
        return "missing_key"
    value = parsed[key]
    if not isinstance(value, str):
        return f"wrong_type({type(value).__name__})"
    if not value.strip():
        return "empty_value"
    return None


def _parse_essay_json(raw: str) -> EssayParse:
    """LLM 応答テキストから dict を取り出す。

    失敗時は ``reason`` に機械可読な理由を入れて返す:

      ``empty_response``            応答が空
      ``no_json_object``            ``{`` が見つからない
      ``decode_error: <msg>``       json.JSONDecodeError
      ``not_dict(<type>)``          JSON だが dict でない
      ``missing_key:<キー>``        必須キーが無い
      ``empty_value:<キー>``        必須キーが空文字
      ``wrong_type(<型>):<キー>``   必須キーが str でない

    ``RESCUABLE_KEYS`` だけが壊れている場合は失敗とせず、そのキーを落とした
    dict と ``rescued`` を返す（呼び出し側が代替値を埋める）。
    """
    if not raw:
        return EssayParse(reason="empty_response")
    text = _FENCE_RE.sub("", raw).strip()
    if not text.startswith("{"):
        idx = text.find("{")
        if idx < 0:
            return EssayParse(reason="no_json_object")
        text = text[idx:]
    end = text.rfind("}")
    if end >= 0:
        text = text[: end + 1]
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as e:
        # 位置つきで残す。どの引用符で転んだかの手掛かりになる。
        return EssayParse(reason=f"decode_error: {e.msg} at char {e.pos}")
    if not isinstance(parsed, dict):
        return EssayParse(reason=f"not_dict({type(parsed).__name__})")

    problems: dict[str, str] = {}
    for key in REQUIRED_KEYS:
        kind = _classify_key(parsed, key)
        if kind:
            problems[key] = kind
    if problems:
        blocking = {k: v for k, v in problems.items() if k not in RESCUABLE_KEYS}
        if blocking:
            return EssayParse(
                reason=", ".join(f"{v}:{k}" for k, v in sorted(blocking.items()))
            )
        # 救済可能なキーだけが壊れている
        good = {
            k: parsed[k].strip() for k in REQUIRED_KEYS if k not in problems
        }
        return EssayParse(
            data=good,
            reason=", ".join(f"{v}:{k}" for k, v in sorted(problems.items())),
            rescued=tuple(sorted(problems)),
        )
    return EssayParse(data={k: parsed[k].strip() for k in REQUIRED_KEYS})


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

    ``logs/page1_v3_fallback_raw_<日付>.txt`` として書き、daily.yml の
    ``audit-logs-<日付>`` artifact に収録される（retention 90 日）。
    ``gh run download`` で取得して parse 失敗の原因を追う。

    C24 (2026-05-24) がこの命名規約を入れた時、docstring には「GHA workflow が
    audit-logs artifact に同梱できるよう」とだけ書かれ、**workflow 側の
    ``path:`` に追加する作業が漏れていた**。git add にも .gitignore にも無く、
    ファイルは runner 上に書かれて捨てられていた。2026-08-19 の休載で初めて
    必要になり、存在しないことが判明（3 ヶ月間一度も機能していなかった）。
    C172 で daily.yml に実際に追加した。repo には commit しない（診断専用で
    cache 参照経路が無いため、artifact 90 日保持で足りる）。
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


def _log_rescue(parse: EssayParse, *, attempt: int) -> None:
    """部分救済したことを必ず記録する（C156 の教訓）.

    救済は「壊れていたのに紙面が出た」状態なので、黙って通すと破損が
    可視化されない。
    """
    if not parse.rescued:
        return
    print(
        f"[page1_v3] WARN: attempt {attempt} は "
        f"{'/'.join(parse.rescued)} が壊れていたため代替値で救済しました "
        f"(reason: {parse.reason})。論考本文は採用します",
        file=sys.stderr,
    )


def _fallback_quote(week: WeekContext) -> str:
    """``quote_excerpt`` を救済する時の代替（monthly_pivotal.json 由来）."""
    a = week.article
    return (a.get("key_quote_ja") or a.get("key_quote") or "").strip()


def _build_essay_result(
    week: WeekContext, parsed: dict, cost: float,
    *, rescued: tuple[str, ...] = (),
) -> EssayResult:
    """parse 成功時の EssayResult 構築（generate_essay の 2 経路で共有）.

    C172: ``rescued`` に入ったキーは parsed に無いので代替値で埋める。
    """
    quote = parsed.get("quote_excerpt")
    if not quote:
        quote = _fallback_quote(week)
    return EssayResult(
        angle_label=_angle_label_text(week),
        daily_question=parsed["daily_question"],
        essay_title=parsed["essay_title"],
        body=parsed["body"],
        annotation_label=parsed["annotation_label"],
        annotation_body=parsed["annotation_body"],
        quote_excerpt=quote,
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
        ``logs/`` ディレクトリ。daily.yml の audit-logs artifact に収録される
        （C172 で実収録。それ以前は書かれるだけで捨てられていた）。
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
    p1 = _parse_essay_json(raw)
    if p1.data is not None:
        _log_rescue(p1, attempt=1)
        return _build_essay_result(week, p1.data, cost, rescued=p1.rescued)

    # ----- Attempt 2: JSON parse 失敗時の 1 回 retry -----
    print(
        f"[page1_v3] essay parse failed on attempt 1 "
        f"(raw {len(raw)} chars, reason: {p1.reason}), retrying once",
        file=sys.stderr,
    )
    try:
        resp2 = caller(system=system, user=user)
    except Exception as e:  # noqa: BLE001
        return _make_fallback(
            week, target_date,
            f"retry call exception {type(e).__name__} "
            f"(attempt 1 reason: {p1.reason})",
            raw=raw, out_dir=out_dir,
        )
    raw2 = getattr(resp2, "text", "") or ""
    cost2 = float(getattr(resp2, "cost_usd", 0.0) or 0.0)
    p2 = _parse_essay_json(raw2)
    if p2.data is not None:
        print(
            f"[page1_v3] essay parse succeeded on attempt 2 "
            f"(retry cost ${cost2:.4f}, total ${cost + cost2:.4f})",
            file=sys.stderr,
        )
        _log_rescue(p2, attempt=2)
        return _build_essay_result(
            week, p2.data, cost + cost2, rescued=p2.rescued,
        )

    # ----- 両方失敗: fallback + 両 attempt の raw を連結保存 -----
    # C172: 両 attempt の理由を残す。同じ理由なら入力データ側（例えば主軸記事の
    # 引用符）が原因で、違う理由なら生成の揺らぎ、という切り分けができる。
    combined = (
        f"=== attempt 1 ({len(raw)} chars, reason: {p1.reason}) ===\n{raw}\n\n"
        f"=== attempt 2 ({len(raw2)} chars, reason: {p2.reason}) ===\n{raw2}"
    )
    return _make_fallback(
        week, target_date,
        f"parse failed both attempts (1: {p1.reason} / 2: {p2.reason})",
        raw=combined, out_dir=out_dir,
    )
