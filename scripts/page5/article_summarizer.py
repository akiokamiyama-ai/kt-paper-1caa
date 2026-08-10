"""第5面 AIかみやま参照記事の日本語サマリ生成（C155, Sprint 13, 2026-08-10）。

第5面が「AIかみやまの一筆」100% になったのに伴い、一筆が論評している記事の
日本語サマリを併載する。読者が「何への論評か」を紙面上で完結して理解できる
ようにするため。

設計上の位置づけ:
    一筆本文は miibo（AIかみやまのペルソナを持つ外部エージェント）が生成する。
    本 module のサマリは **Tribune 側 = Anthropic API** で生成し、両者を並べて
    表示する。声を混ぜないため、サマリは「事実の要約」に徹して評価・解釈を
    入れない（AIかみやまの一筆と役割が被らないようにする）。

品質基準は第6面のコラム同等:
    * 本文を消化した日本語（原文の機械翻訳ではない）
    * 300-400 字目安
    * 本文が取れない / LLM 失敗時は description の truncate に fallback し、
      紙面は決して破綻させない

旧 Today's Headlines の LLM 要約は BBC 記事限定で本文を取りに行き、
``BbcArticleScraper`` の CSS 依存が壊れて 10 日間 0 件稼働という状態だった
（C155a）。その反省から本 module は **ソースを限定せず汎用の本文抽出**を使い、
本文が取れなくても description だけで要約を試みる二段構えにする。
"""

from __future__ import annotations

import re
import sys

from ..lib import llm

DEFAULT_MODEL = llm.DEFAULT_MODEL
DEFAULT_MAX_TOKENS = 800
DEFAULT_TEMPERATURE = 0.3

SUMMARY_TAG = "page5.article_summary"

# 目安 300-400 字。上限は暴走防止（末尾「…」の余裕込み）。
TARGET_MIN_CHARS = 300
TARGET_MAX_CHARS = 400
HARD_MAX_CHARS = 480

# 本文抽出をあきらめて description のみで要約する閾値。
# description すらこれ未満なら LLM を呼ばず truncate fallback に倒す。
MIN_INPUT_CHARS = 80

# LLM に渡す入力の上限（コスト暴走防止）。
INPUT_EXCERPT_LIMIT = 3000

SUMMARY_SYSTEM = """あなたは朝刊の編集者です。与えられた記事を、読者が「何の記事か」を正確に理解できる日本語サマリにしてください。

【役割の分担】
このサマリの隣には、同じ記事に対する「AIかみやまの一筆」（論評）が並びます。
あなたの仕事は論評ではなく、その論評を読むための土台を作ることです。

【要約の指針】
- 事実を丁寧に。「誰が・何を・なぜ」を必ず含める
- 解釈・評価・意見・提言は一切加えない（それは一筆の役割）
- 原文が英語でも、こなれた日本語で書く。直訳調にしない
- 300-400 字目安
- サマリ本文のみを出力。前置き・後置き・見出し・括弧書き・コードフェンスは不要"""

SUMMARY_USER_TEMPLATE = """記事タイトル: {title}
ソース: {source}

本文または概要:
{body}"""

_HTML_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def _strip_html(text: str | None) -> str:
    if not text:
        return ""
    import html as _html
    no_tags = _HTML_TAG_RE.sub(" ", text)
    return _WS_RE.sub(" ", _html.unescape(no_tags)).strip()


def truncate_to_chars(text: str, limit: int) -> str:
    """``limit`` 字で切り、切り詰めた場合のみ末尾に「…」を付ける。"""
    t = (text or "").strip()
    if len(t) <= limit:
        return t
    return t[:limit].rstrip() + "…"


def _build_input_text(article: dict) -> str:
    """要約に渡すテキストを組み立てる。

    ``body`` があれば優先（Stage 1 が本文を持つ記事はここに入る）、
    無ければ ``description``。両方あれば連結して情報量を稼ぐ。
    """
    body = _strip_html(article.get("body"))
    desc = _strip_html(
        article.get("description") or article.get("desc_ja") or ""
    )
    if body and desc and desc[:40] not in body:
        combined = f"{desc}\n\n{body}"
    else:
        combined = body or desc
    return combined[:INPUT_EXCERPT_LIMIT]


def summarize_article(
    article: dict,
    *,
    llm_caller=None,
) -> dict:
    """参照記事の日本語サマリを返す。

    Returns::

        {
            "summary": str,        # 紙面に出す本文（必ず非空、fallback 込み）
            "is_fallback": bool,   # LLM を使えず truncate に落ちたか
            "cost_usd": float,
        }

    ``llm_caller`` はテスト用の差し替え口（``(system, user) -> str``）。
    """
    title = (article.get("title_ja") or article.get("title") or "").strip()
    source = (article.get("source_name") or "").strip()
    raw = _build_input_text(article)

    fallback_text = truncate_to_chars(
        _strip_html(article.get("description") or article.get("desc_ja") or ""),
        TARGET_MAX_CHARS,
    )

    if len(raw) < MIN_INPUT_CHARS:
        print(
            f"[page5/summary] 入力が短すぎる ({len(raw)} 字 < {MIN_INPUT_CHARS}) "
            "— description truncate に fallback",
            file=sys.stderr,
        )
        return {"summary": fallback_text, "is_fallback": True, "cost_usd": 0.0}

    user = SUMMARY_USER_TEMPLATE.format(title=title, source=source, body=raw)

    try:
        if llm_caller is not None:
            text = llm_caller(SUMMARY_SYSTEM, user)
            cost = 0.0
        else:
            resp = llm.call_claude_with_retry(
                system=SUMMARY_SYSTEM,
                user=user,
                model=DEFAULT_MODEL,
                max_tokens=DEFAULT_MAX_TOKENS,
                tag=SUMMARY_TAG,
            )
            text = resp.text
            cost = float(getattr(resp, "cost_usd", 0.0) or 0.0)
    except Exception as e:  # noqa: BLE001 — 紙面を落とさない
        print(
            f"[page5/summary] LLM 失敗 ({type(e).__name__}: {e}) "
            "— description truncate に fallback",
            file=sys.stderr,
        )
        return {"summary": fallback_text, "is_fallback": True, "cost_usd": 0.0}

    summary = _strip_html(text)
    if not summary:
        print(
            "[page5/summary] LLM 応答が空 — description truncate に fallback",
            file=sys.stderr,
        )
        return {"summary": fallback_text, "is_fallback": True, "cost_usd": cost}

    return {
        "summary": truncate_to_chars(summary, HARD_MAX_CHARS),
        "is_fallback": False,
        "cost_usd": cost,
    }
