"""Page 2 (社長の朝会) selection and morning-question pipeline.

Implements the design in ``docs/page2_prompts_v1.md`` v1.0 — a 2-step LLM
pipeline that chooses one article per company (Cocolomi / Human Energy /
Web-Repo) and generates a 40〜80 char "今朝の問い" for each.

Pipeline (per ``docs/page2_prompts_v1.md`` §3):

* Stage 0 (input): Stage 1 → Stage 2 → Stage 3 を通った scored articles
  のリスト。各 dict は ``url`` / ``title`` / ``description`` / ``body`` /
  ``source_name`` / ``final_score`` (Stage 3 産) / 美意識スコア各種を持つ。
* Step 1: 経営的含意 (managerial_implication) と規制動向
  (regulatory_signal) を 0–10 で評価（社別バッチ、cache_control 別）。
* page2_final_score 計算: ``final_score × 0.30 + 含意 × 10 × 0.40 +
  規制動向 × 10 × 0.30``。
* 5段階フォールバックで各社 Top 1 を選定（``docs/page2_prompts_v1.md`` §6.5）。
* Step 2: 各社 Top 1 に対して「今朝の問い」を1コール1記事で生成。
* ``logs/page2_scores_YYYY-MM-DD.json`` に書き出し（``selection_log``
  でフォールバック段階を毎日トレース）。

Public entry points
-------------------
* ``compute_page2_score(article)``               — 1 article のスコア計算
* ``evaluate_management_relevance(articles, key)`` — Step 1 batch
* ``select_page2_articles(scored, fetcher_fn, threshold)`` — 5段階選定
* ``generate_morning_question(article, key)``    — Step 2 1記事
* ``run_page2_pipeline(scored, fetcher_fn, ...)`` — 全自動オーケストレーション
* ``main(argv)``                                  — ``python3 -m scripts.selector.page2``
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable

from ..lib import llm, llm_usage
from .source_registry import SourceRegistry, build_registry
from .stage1 import run_stage1
from .stage2 import run_stage2
from .stage3 import integrate_scores

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SOURCES_DIR = PROJECT_ROOT / "sources"
LOG_DIR = PROJECT_ROOT / "logs"
COMPANIES_CONTEXT_PATH = PROJECT_ROOT / "docs" / "companies_context_v1.md"

DEFAULT_MODEL = llm.DEFAULT_MODEL
DEFAULT_MAX_TOKENS_STEP1 = 2048
DEFAULT_MAX_TOKENS_STEP2 = 512

DEFAULT_BATCH_SIZE_STEP1 = 10
PER_COMPANY_CANDIDATE_CAP = 10  # docs/page2_prompts_v1.md §8.5

# 初動は 40 で開始、フォールバック発動頻度を見て Sprint 2 完了時に
# 50 への引き上げを検討。docs/page2_prompts_v1.md §6.5 では最終形 50 が
# 目安として記載されているが、初期運用は緩める。
DEFAULT_THRESHOLD = 40.0

MODE_A_DESC_THRESHOLD = 80
BODY_EXCERPT_LIMIT = 800

COMPANY_KEYS: tuple[str, ...] = ("cocolomi", "human_energy", "web_repo")

# 短縮キー → Source.category（companies.md の sub-category）
SHORT_TO_CATEGORY: dict[str, str] = {
    "cocolomi":     "companies:Cocolomi",
    "human_energy": "companies:Human Energy",
    "web_repo":     "companies:Web-Repo",
}

# Stage 4 cross-industry pre-filter: business.md / geopolitics.md の High+Medium
# から取得した記事のうち、各社の事業文脈と接続するキーワードを title または
# description に含むものだけを Step 1 評価対象に絞る。
# キーワード設計は Sprint 2 Step C で神山さん指定（page2_prompts_v1.md §6.5
# の「該当社の事業文脈に関連する記事を LLM 判定で選定」を、まず軽量な
# キーワード pre-filter で実装）。
CROSS_INDUSTRY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "cocolomi": (
        "生成AI", "生成人工知能", "生成型AI", "AI規制",
        "AI事業者ガイドライン", "AI戦略", "OpenAI", "Anthropic",
        "Claude", "Gemini", "ChatGPT",
    ),
    "human_energy": (
        "組織開発", "心理的安全性", "エンゲージメント",
        "リスキリング", "越境学習", "対話型組織開発",
        "research on management", "Edgar Schein",
    ),
    "web_repo": (
        "フランチャイズ", "FC", "franchise", "加盟店",
        "本部", "JFA", "公正取引委員会", "FC契約",
        "24時間営業", "メガフランチャイジー", "マスターフランチャイズ",
    ),
}

# Cross-industry stage で fetch する priority。High だけでなく Medium も含める
# ことで東洋経済オンライン・ITmedia ビジネスオンライン等の主要メディアを捕捉。
CROSS_INDUSTRY_PRIORITIES: tuple[str, ...] = ("high", "medium")
# 短縮キー → 人間可読社名（log・stderr 用）
SHORT_TO_DISPLAY: dict[str, str] = {
    "cocolomi":     "Cocolomi",
    "human_energy": "Human Energy",
    "web_repo":     "Web-Repo",
}
# companies_context_v1.md 内の見出しテキスト
CONTEXT_HEADERS: dict[str, str] = {
    "cocolomi":     "## 1. Cocolomi",
    "human_energy": "## 2. Human Energy",
    "web_repo":     "## 3. Web-Repo",
}

# ---------------------------------------------------------------------------
# System prompt templates (placeholder = {{COMPANY_CONTEXT}})
#
# .replace() でプレースホルダ置換するため、JSON サンプル中の `{` / `}` は
# エスケープ不要。docs/page2_prompts_v1.md §4.2 / §5.2 と同期する。
# ---------------------------------------------------------------------------

STEP1_SYSTEM_TEMPLATE = """あなたは Kamiyama Tribune 第2面「社長の朝会」の評価アシスタントです。

第2面は、神山晃男氏が経営するグループ3社（Cocolomi・Human Energy・Web-Repo）に関わる今朝のニュースを、各社1本ずつ届けるための面です。あなたの仕事は、与えられた記事1本に対し、**指定された1社の事業判断にとっての価値** を「経営的含意」「規制動向」の2軸で 0–10 評価し、理由を簡潔な日本語で添えることです。

【担当する社の事業文脈】

{{COMPANY_CONTEXT}}

## 評価軸

### 経営的含意（0–10）

この記事は、上記事業文脈に照らして、**当該社の経営判断・戦略・顧客対話・プロダクト改善** にどれだけ直接的な示唆を与えるか？

スコアバンド：
- 9–10：今朝の判断・行動に直結する具体的なシグナル（数字・期限・契約構造の変化等）
- 6–8：3〜6ヶ月単位の戦略アジェンダに加わる材料
- 3–5：業界の流れの観察、間接的に効く可能性
- 0–2：当該社の事業判断に関係しない／一般経済記事の域

### 規制動向（0–10）

この記事は、当該社の **事業環境を変えうる規制・法改正・判例・公的ガイドライン** をどれだけ明示的に扱っているか？

スコアバンド：
- 9–10：当該社の事業領域の規制・法改正・判例・ガイドライン公布を直接報じる
- 6–8：当該社の事業領域に隣接する規制動向、または業界協会の自主規制レベル
- 3–5：規制の気配があるが、業界共通の総論レベル
- 0–2：規制動向との接点が見当たらない

## 共通ルール

- スコアは 0–10 の整数のみ。小数・範囲外は不可。
- 評価に迷う場合は控えめに（中央値 3–4 寄り）。reason で迷いを示唆する。
- キーワードヒット数で機械的に決めず、記事全体の趣旨と事業文脈との接続を読む。
- ソース名・媒体権威から推測しない。記事内容と事業文脈のみが判定根拠。
- 「経営的含意」と「規制動向」は独立評価。一方が高いから他方も高くなるとは限らない。
- 単なる経済記事・技術記事・業界統計記事は、上記事業文脈との接続が明示的でなければ低スコア寄り。

## 出力フォーマット

以下のJSONのみで返答（前置き・後置き・コードフェンス禁止）。

{
  "evaluations": [
    {
      "article_id": "art_001",
      "scores": {
        "managerial_implication": 0–10の整数,
        "regulatory_signal": 0–10の整数
      },
      "reasons": {
        "managerial_implication": "日本語で1〜2文、80字以内",
        "regulatory_signal": "日本語で1〜2文、80字以内"
      }
    }
  ]
}

厳格な制約：
- evaluations 配列の長さは入力記事数と一致させる。
- 各 article_id は入力されたIDをそのまま echo する。
- 2項目すべて必須、追加フィールド禁止。
- スコアは整数、範囲 [0, 10]。
- reason は空文字禁止、日本語、80字以内目安。
- JSON 以外の出力禁止。
"""

STEP2_SYSTEM_TEMPLATE = """あなたは Kamiyama Tribune 第2面「社長の朝会」の編集アシスタントです。

第2面は、神山晃男氏が経営するグループ3社（Cocolomi・Human Energy・Web-Repo）に関わる今朝のニュースを、各社1本ずつ届けるための面です。あなたの仕事は、与えられた1本の記事と事業文脈・既存の評価結果を踏まえて、神山さんに投げかける **「今朝の問い」** を1つ生成することです。

## 「今朝の問い」の質的基準

- 長さ：日本語 40〜80字（半角は0.5、全角は1で換算）
- 形式：**疑問形**（「〜か？」「〜だろうか？」「〜はどれか？」「〜できるか？」等）
- **命令形にしない**（「〜すべき」「〜せよ」は禁止）。判断は神山さんに委ねる
- 構造：**観察→含意→問い** の3層を1問に圧縮する
  - 観察 = 記事が報じている事実の核
  - 含意 = それが当該社の事業文脈にとって何を意味するか
  - 問い = 神山さんが今朝考えるべき選択・判断の焦点
- **具体性を優先**：時期・数字・対象（「7月までに」「上位50案件」「3ページ・1クライアント」等）を含むほうが「問い」として強くなる
- **原語固有名詞**は積極的に残す（Cocolomi、Edgar Schein、JFA、Foresight 等の翻訳は不要）
- 抽象論で終わらない（「重要だろうか？」「考えるべきか？」のような薄い問いは弱い）

## 例（創刊号 4/25 の3社別「今朝の問い」）

### Cocolomi 例（経産省ガイドライン記事への問い）

> 7月までに執筆・公開できれば、競合がリストの存在に気付く前にCocolomiを参照リストの中に置けるであろう、製造業の事例研究2本はどれか？

観察＝補助金要件に「実績のあるパートナー」明記 / 含意＝参照リストへの早期掲載が好機 / 問い＝執筆対象事例の選択。約 70字。

### Human Energy 例（Edgar Schein 後継ラボのフィールドスタディ記事への問い）

> Human Energy版「フィールドスタディ」のパンフレット——3ページ、1クライアント、観察記録（証言ではなく）——は、次回の営業レビューまでに草稿化できるか？

観察＝海外で対話的計測のフィールドスタディが可視化された / 含意＝HE が既に近いことをやっている / 問い＝言語化・パンフレット化の実行可否。約 80字。

### Web-Repo 例（東京地裁・FC開示基準厳格化記事への問い）

> 「この見込み数字が何を意味するか」を平易に解説するサイドバーを付加した場合、最も恩恵が大きいのは Web-Repo 上のどの上位50案件か？ そしてそのコストは？

観察＝開示基準厳格化判決 / 含意＝透明性プレミアムが急上昇する瞬間 / 問い＝サイドバー追加対象の50案件選定とコスト見積。約 75字。

## 担当する社の事業文脈

{{COMPANY_CONTEXT}}

## 共通ルール

- 「観察→含意→問い」を意識せよとは記事に明示せず、結果として1問の中にこれらが圧縮されている状態を作る。
- 既存の Stage 2 美意識評価・Step 1 の経営含意/規制動向評価は、問いの「含意」部分を支える根拠として参照する。ただし「美意識1スコアが高いので…」のような評価値の直接引用はしない（読者には冗長）。
- 神山さんは3社の経営者である前提。読者プロファイルとして、規模・派手さより構造・深さ・他者性を重視する。
- 記事に明記されていない事実（社名・数字・時期・施策の具体）を作話しない。記事と事業文脈の範囲内でのみ問いを構成する。

## 出力フォーマット

以下の JSON のみで返答（前置き・後置き・コードフェンス・引用符付与すべて禁止）。

{
  "article_id": "art_001",
  "morning_question": "ここに40〜80字の問いを1つ"
}

厳格な制約：
- morning_question は日本語、40〜80字、疑問形（？で終わる）。
- ダブルクォート内の改行は禁止。
- JSON 以外の出力禁止。
"""

FALLBACK_QUESTION = "（本日の問い生成に失敗しました）"


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class Step1Eval:
    article_id: str
    managerial_implication: int
    regulatory_signal: int
    managerial_implication_reason: str
    regulatory_signal_reason: str


@dataclass
class EvaluationError:
    stage: str
    article_id: str
    url: str | None
    error_type: str
    raw_response_excerpt: str
    occurred_at: str


@dataclass
class CompanySelection:
    company_key: str
    article: dict | None       # None if no_article_today
    page2_final_score: float | None
    morning_question: str | None
    stage_used: str             # "high" | "medium" | "reference" | "cross_industry" | "none"
    threshold_passed: bool
    fallback_reason: str | None


@dataclass
class Page2Result:
    selections: dict[str, CompanySelection] = field(default_factory=dict)
    errors: list[EvaluationError] = field(default_factory=list)
    threshold: float = DEFAULT_THRESHOLD
    cost_usd: float = 0.0
    today: date | None = None


# ---------------------------------------------------------------------------
# Module-level caches
# ---------------------------------------------------------------------------

_REGISTRY: SourceRegistry | None = None
_COMPANIES_CONTEXT_TEXT: str | None = None


def _get_registry() -> SourceRegistry:
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = build_registry(SOURCES_DIR)
    return _REGISTRY


def _get_companies_context_text() -> str:
    global _COMPANIES_CONTEXT_TEXT
    if _COMPANIES_CONTEXT_TEXT is None:
        _COMPANIES_CONTEXT_TEXT = COMPANIES_CONTEXT_PATH.read_text(encoding="utf-8")
    return _COMPANIES_CONTEXT_TEXT


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )


def extract_company_context(company_key: str, *, doc_text: str | None = None) -> str:
    """Slice the per-company section out of companies_context_v1.md and
    rename ``## 1. Cocolomi（…）`` → ``## 事業文脈``.

    Per docs/page2_prompts_v1.md §9.3, also strips any leading bracketed
    sub-title to keep the section header simple.
    """
    if company_key not in CONTEXT_HEADERS:
        raise KeyError(f"unknown company_key {company_key!r}")
    text = doc_text if doc_text is not None else _get_companies_context_text()
    start_marker = CONTEXT_HEADERS[company_key]
    start = text.find(start_marker)
    if start < 0:
        raise ValueError(
            f"section not found in companies_context for {company_key!r}: "
            f"looking for {start_marker!r}"
        )
    # Find the trailing "---" separator that ends this section.
    end = text.find("\n---\n", start)
    if end < 0:
        # Fallback: take to end of doc.
        section = text[start:]
    else:
        section = text[start:end]

    # Replace the first line ("## 1. Cocolomi（…）") with "## 事業文脈"
    lines = section.splitlines()
    if lines and lines[0].startswith("## "):
        lines[0] = "## 事業文脈"
    return "\n".join(lines).rstrip()


def _build_step1_system(company_key: str) -> str:
    context = extract_company_context(company_key)
    return STEP1_SYSTEM_TEMPLATE.replace("{{COMPANY_CONTEXT}}", context)


def _build_step2_system(company_key: str) -> str:
    context = extract_company_context(company_key)
    return STEP2_SYSTEM_TEMPLATE.replace("{{COMPANY_CONTEXT}}", context)


def _category_for(article: dict, registry: SourceRegistry) -> str | None:
    """Look up Source.category from the article's source_name."""
    if "category" in article and article["category"]:
        return article["category"]
    name = article.get("source_name")
    if not name:
        return None
    src = registry.sources_by_name.get(name)
    return src.category if src else None


def _attach_category(article: dict, registry: SourceRegistry) -> dict:
    cat = _category_for(article, registry)
    if cat is not None:
        article["category"] = cat
    return article


def _truncate_body(body: str, limit: int = BODY_EXCERPT_LIMIT) -> str:
    if not body or len(body) <= limit:
        return body or ""
    excerpt = body[:limit]
    for sep in ("。", "\n", "．", "."):
        idx = excerpt.rfind(sep)
        if idx >= limit // 2:
            return excerpt[: idx + 1]
    return excerpt


def _format_step1_article_block(article_id: str, art: dict) -> str:
    title = (art.get("title") or "").strip()
    source = (art.get("source_name") or "").strip()
    description = (art.get("description") or "").strip()
    body = (art.get("body") or "").strip()
    lines = [f"[{article_id}]", f"title: {title}", f"source: {source}"]
    if description:
        lines.append(f"description: {description}")
    if len(description) < MODE_A_DESC_THRESHOLD and body:
        excerpt = _truncate_body(body)
        if excerpt:
            lines.append(f"body: {excerpt}")
    return "\n".join(lines)


def _build_step1_user_message(articles: list[dict], ids: list[str]) -> str:
    n = len(articles)
    header = (
        f"以下の記事 {n} 本について、システムプロンプトで指定された2軸"
        "（経営的含意・規制動向）を評価してください。"
    )
    blocks = "\n\n".join(
        _format_step1_article_block(aid, art) for aid, art in zip(ids, articles)
    )
    return f"{header}\n\n{blocks}\n\nJSON のみで返答してください。"


def _summarize_aesthetic_reasons(article: dict) -> str:
    """Stage 2 reasons (5 項目) を改行区切りで連結。docs/page2_prompts §5.3。"""
    reasons = article.get("evaluation_reason") or {}
    lines = []
    for key, label in (
        ("1", "美意識1（構造×細部）"),
        ("3", "美意識3（学問領域横断）"),
        ("5", "美意識5（他者性）"),
        ("6", "美意識6（マイノリティ価値）"),
        ("8", "美意識8（行動経済学）"),
    ):
        r = reasons.get(key)
        if r:
            lines.append(f"  - {label}: {r}")
    return "\n".join(lines) if lines else "  （Stage 2 reasons なし）"


def _build_step2_user_message(article: dict) -> str:
    article_id = "art_001"  # Step 2 は単記事なので固定
    title = (article.get("title") or "").strip()
    source = (article.get("source_name") or "").strip()
    description = (article.get("description") or "").strip()
    body = (article.get("body") or "").strip()

    lines = [
        "以下の記事1本に対し、システムプロンプトで指定された「今朝の問い」を1つ生成してください。",
        "",
        f"[{article_id}]",
        f"title: {title}",
        f"source: {source}",
    ]
    if description:
        lines.append(f"description: {description}")
    if len(description) < MODE_A_DESC_THRESHOLD and body:
        excerpt = _truncate_body(body)
        if excerpt:
            lines.append(f"body: {excerpt}")

    aesthetic_summary = _summarize_aesthetic_reasons(article)
    aes1 = article.get("美意識1", "?")
    aes3 = article.get("美意識3", "?")
    aes5 = article.get("美意識5", "?")
    aes6 = article.get("美意識6", "?")
    aes8 = article.get("美意識8", "?")
    mi = article.get("managerial_implication", "?")
    mi_r = article.get("managerial_implication_reason", "")
    rs = article.get("regulatory_signal", "?")
    rs_r = article.get("regulatory_signal_reason", "")
    final = article.get("page2_final_score", "?")

    lines += [
        "",
        "【既存の評価結果】",
        f"- 美意識スコア（神山美意識）：1={aes1} / 3={aes3} / 5={aes5} / 6={aes6} / 8={aes8}",
        "- 美意識評価の根拠：",
        aesthetic_summary,
        f"- 経営的含意：{mi} — {mi_r}",
        f"- 規制動向：{rs} — {rs_r}",
        f"- 第2面 final_score：{final}",
        "",
        "JSON のみで返答してください。",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Step 1: 経営的含意・規制動向 評価
# ---------------------------------------------------------------------------

_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*\n?|\n?```\s*$", re.IGNORECASE | re.MULTILINE)


def _parse_step1_response(raw_text: str) -> tuple[dict | None, str | None]:
    if not raw_text:
        return None, "empty_response"
    text = _FENCE_RE.sub("", raw_text).strip()
    if not text.startswith("{"):
        idx = text.find("{")
        if idx < 0:
            return None, "no_json_object_found"
        text = text[idx:]
    try:
        return json.loads(text), None
    except json.JSONDecodeError as e:
        return None, f"json_decode_error: {e.msg}"


def _clamp_score(v: Any) -> tuple[int, bool]:
    try:
        x = int(round(float(v)))
    except (TypeError, ValueError):
        return 3, True
    if x < 0:
        return 0, True
    if x > 10:
        return 10, True
    return x, False


def _validate_step1_eval(
    ev: dict,
    expected_id: str,
    raw_excerpt: str,
) -> tuple[Step1Eval, list[EvaluationError]]:
    errors: list[EvaluationError] = []
    if not isinstance(ev, dict):
        errors.append(EvaluationError(
            stage="step1", article_id=expected_id, url=None,
            error_type="not_an_object", raw_response_excerpt=raw_excerpt[:200],
            occurred_at=_now_iso(),
        ))
        return _fallback_step1(expected_id, "evaluation_failed"), errors

    aid = ev.get("article_id")
    if aid != expected_id:
        errors.append(EvaluationError(
            stage="step1", article_id=expected_id, url=None,
            error_type="article_id_mismatch",
            raw_response_excerpt=f"got article_id={aid!r}",
            occurred_at=_now_iso(),
        ))

    raw_scores = ev.get("scores") or {}
    raw_reasons = ev.get("reasons") or {}
    if not isinstance(raw_scores, dict):
        raw_scores = {}
    if not isinstance(raw_reasons, dict):
        raw_reasons = {}

    score_keys = ("managerial_implication", "regulatory_signal")
    cleaned_scores: dict[str, int] = {}
    cleaned_reasons: dict[str, str] = {}
    for key in score_keys:
        if key not in raw_scores:
            cleaned_scores[key] = 3
            errors.append(EvaluationError(
                stage="step1", article_id=expected_id, url=None,
                error_type=f"missing_score:{key}",
                raw_response_excerpt=raw_excerpt[:200],
                occurred_at=_now_iso(),
            ))
        else:
            v, modified = _clamp_score(raw_scores[key])
            cleaned_scores[key] = v
            if modified:
                errors.append(EvaluationError(
                    stage="step1", article_id=expected_id, url=None,
                    error_type=f"score_clamped:{key}",
                    raw_response_excerpt=f"original={raw_scores[key]!r}",
                    occurred_at=_now_iso(),
                ))
        r = raw_reasons.get(key)
        if not isinstance(r, str) or not r.strip():
            cleaned_reasons[key] = (
                "missing_from_response" if key not in raw_reasons else "(no_reason_provided)"
            )
            errors.append(EvaluationError(
                stage="step1", article_id=expected_id, url=None,
                error_type=f"missing_or_empty_reason:{key}",
                raw_response_excerpt=raw_excerpt[:200] if key not in raw_reasons else "",
                occurred_at=_now_iso(),
            ))
        else:
            cleaned_reasons[key] = r.strip()

    return Step1Eval(
        article_id=expected_id,
        managerial_implication=cleaned_scores["managerial_implication"],
        regulatory_signal=cleaned_scores["regulatory_signal"],
        managerial_implication_reason=cleaned_reasons["managerial_implication"],
        regulatory_signal_reason=cleaned_reasons["regulatory_signal"],
    ), errors


def _fallback_step1(article_id: str, reason: str) -> Step1Eval:
    return Step1Eval(
        article_id=article_id,
        managerial_implication=3,
        regulatory_signal=3,
        managerial_implication_reason=reason,
        regulatory_signal_reason=reason,
    )


def evaluate_management_relevance(
    articles: list[dict],
    company_key: str,
    *,
    model: str = DEFAULT_MODEL,
) -> tuple[list[Step1Eval], list[EvaluationError], float]:
    """Run Step 1 over a batch of articles for one company.

    Returns ``(evaluations, errors, cost_usd)``. evaluations preserves the
    input order. cost_usd is the LLM cost for this batch (single API call
    when ``len(articles) <= DEFAULT_BATCH_SIZE_STEP1``).
    """
    if not articles:
        return [], [], 0.0

    if company_key not in COMPANY_KEYS:
        raise ValueError(f"unknown company_key {company_key!r}")

    # Auto-batch if exceeds DEFAULT_BATCH_SIZE_STEP1.
    if len(articles) > DEFAULT_BATCH_SIZE_STEP1:
        all_evals: list[Step1Eval] = []
        all_errors: list[EvaluationError] = []
        total_cost = 0.0
        for i in range(0, len(articles), DEFAULT_BATCH_SIZE_STEP1):
            batch = articles[i : i + DEFAULT_BATCH_SIZE_STEP1]
            evs, errs, cost = evaluate_management_relevance(
                batch, company_key, model=model
            )
            all_evals.extend(evs)
            all_errors.extend(errs)
            total_cost += cost
        return all_evals, all_errors, total_cost

    system_prompt = _build_step1_system(company_key)
    ids = [f"art_{i + 1:03d}" for i in range(len(articles))]
    user_msg = _build_step1_user_message(articles, ids)

    parsed: dict | None = None
    parse_err: str | None = None
    last_response: llm.ClaudeResponse | None = None
    raw_excerpt = ""
    cost = 0.0

    for attempt in range(2):
        if attempt == 0:
            attempt_user = user_msg
        else:
            nudge = (
                "\n\n前回の応答は JSON として解析できないか、evaluations 配列の "
                f"長さが {len(articles)} ではありませんでした。"
                "コードフェンス・前置き・後置きをすべて省き、JSON 単体だけを返答してください。"
                f"evaluations の長さは正確に {len(articles)} としてください。"
            )
            attempt_user = user_msg + nudge

        last_response = llm.call_claude_with_retry(
            system=system_prompt,
            user=attempt_user,
            model=model,
            max_tokens=DEFAULT_MAX_TOKENS_STEP1,
            cache_system=True,
        )
        cost += last_response.cost_usd
        raw_excerpt = llm.redact_key((last_response.text or "")[:400])
        parsed, parse_err = _parse_step1_response(last_response.text)

        if parsed is not None:
            evals = parsed.get("evaluations")
            if isinstance(evals, list) and len(evals) == len(articles):
                break
            parse_err = (
                f"array_length_mismatch: got "
                f"{len(evals) if isinstance(evals, list) else 'non-list'}, "
                f"expected {len(articles)}"
            )
            parsed = None

    errors: list[EvaluationError] = []
    if parsed is None or not isinstance(parsed.get("evaluations"), list):
        errors.append(EvaluationError(
            stage="step1", article_id="<batch>", url=None,
            error_type=parse_err or "non_json",
            raw_response_excerpt=raw_excerpt,
            occurred_at=_now_iso(),
        ))
        evals_out = [_fallback_step1(aid, "evaluation_failed") for aid in ids]
    else:
        raw_evals = parsed["evaluations"]
        if len(raw_evals) < len(articles):
            errors.append(EvaluationError(
                stage="step1", article_id="<batch>", url=None,
                error_type=f"array_short:{len(raw_evals)}<{len(articles)}",
                raw_response_excerpt=raw_excerpt,
                occurred_at=_now_iso(),
            ))
            raw_evals = list(raw_evals) + [None] * (len(articles) - len(raw_evals))
        elif len(raw_evals) > len(articles):
            raw_evals = raw_evals[: len(articles)]

        evals_out = []
        for expected_id, ev in zip(ids, raw_evals):
            if ev is None:
                evals_out.append(_fallback_step1(expected_id, "missing_from_response"))
                errors.append(EvaluationError(
                    stage="step1", article_id=expected_id, url=None,
                    error_type="missing_from_response",
                    raw_response_excerpt=raw_excerpt,
                    occurred_at=_now_iso(),
                ))
                continue
            cleaned, ev_errors = _validate_step1_eval(ev, expected_id, raw_excerpt)
            evals_out.append(cleaned)
            errors.extend(ev_errors)

    # Backfill URL into errors using batch ordering for downstream lookups.
    url_by_id = {ids[i]: articles[i].get("url") for i in range(len(articles))}
    for e in errors:
        if e.url is None and e.article_id in url_by_id:
            e.url = url_by_id[e.article_id]

    return evals_out, errors, cost


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def compute_page2_score(article: dict) -> float:
    """page2_final_score = 美意識*0.30 + 経営含意*10*0.40 + 規制動向*10*0.30.

    Missing components default to 0. Result rounded to 2 decimal places,
    clamped to [0, 100].
    """
    aesthetic = article.get("final_score")
    if aesthetic is None:
        aesthetic = 0.0
    try:
        aesthetic_f = float(aesthetic)
    except (TypeError, ValueError):
        aesthetic_f = 0.0

    mi = article.get("managerial_implication", 0)
    rs = article.get("regulatory_signal", 0)
    try:
        mi_f = float(mi)
    except (TypeError, ValueError):
        mi_f = 0.0
    try:
        rs_f = float(rs)
    except (TypeError, ValueError):
        rs_f = 0.0

    score = aesthetic_f * 0.30 + mi_f * 10 * 0.40 + rs_f * 10 * 0.30
    if score < 0:
        score = 0.0
    if score > 100:
        score = 100.0
    return round(score, 2)


# ---------------------------------------------------------------------------
# Selection (5-stage fallback)
# ---------------------------------------------------------------------------

FetcherFn = Callable[..., list[dict]]

_STAGE_ORDER = ("high", "medium", "reference", "cross_industry", "none")


def _enrich_with_step1(
    articles: list[dict], company_key: str
) -> tuple[list[dict], list[EvaluationError], float]:
    """Run Step 1 on a list of articles and merge results back into each dict."""
    if not articles:
        return [], [], 0.0
    capped = articles[:PER_COMPANY_CANDIDATE_CAP]
    evals, errors, cost = evaluate_management_relevance(capped, company_key)
    for art, ev in zip(capped, evals):
        art["managerial_implication"] = ev.managerial_implication
        art["regulatory_signal"] = ev.regulatory_signal
        art["managerial_implication_reason"] = ev.managerial_implication_reason
        art["regulatory_signal_reason"] = ev.regulatory_signal_reason
        art["page2_final_score"] = compute_page2_score(art)
        art.setdefault("company_key_evaluated", company_key)
    return capped, errors, cost


def _cross_industry_keywords(company_key: str) -> tuple[str, ...]:
    """company_key に対応する pre-filter キーワードリストを返す."""
    return CROSS_INDUSTRY_KEYWORDS.get(company_key, ())


def _cross_industry_filter(
    articles: list[dict], company_key: str
) -> list[dict]:
    """pre-filter: title または description にキーワードのいずれかが含まれる記事だけを返す.

    Cross-industry (business.md / geopolitics.md) からの fetch 結果に対し、
    Step 1 LLM 評価コストを抑えるための軽量フィルタ。設計書 page2_prompts_v1.md
    §6.5 で「該当社の事業文脈との接続」を判定する役目。
    """
    keywords = _cross_industry_keywords(company_key)
    if not keywords:
        return list(articles)
    filtered: list[dict] = []
    for art in articles:
        haystack = " ".join(
            (art.get("title") or "", art.get("description") or "")
        )
        if any(k in haystack for k in keywords):
            filtered.append(art)
    return filtered


def _pick_best_above_threshold(
    candidates: list[dict], threshold: float
) -> dict | None:
    if not candidates:
        return None
    qualified = [
        a for a in candidates
        if a.get("page2_final_score") is not None
        and a["page2_final_score"] >= threshold
    ]
    if not qualified:
        return None
    qualified.sort(key=lambda a: a["page2_final_score"], reverse=True)
    return qualified[0]


def select_page2_articles(
    scored_articles: list[dict],
    *,
    fetcher_fn: FetcherFn | None = None,
    threshold: float = DEFAULT_THRESHOLD,
) -> tuple[dict[str, CompanySelection], list[EvaluationError], float]:
    """Run the 5-stage fallback selection per company.

    Returns ``(selections, errors, cost_usd)``. ``selections`` maps each
    company_key to a CompanySelection (article may be None for stage='none').
    """
    registry = _get_registry()
    # Ensure all input articles have category attached.
    for art in scored_articles:
        _attach_category(art, registry)

    selections: dict[str, CompanySelection] = {}
    all_errors: list[EvaluationError] = []
    total_cost = 0.0

    for company_key in COMPANY_KEYS:
        category = SHORT_TO_CATEGORY[company_key]

        # ---------------- Stage 1 (high): use scored_articles in-memory ----
        high_pool = [a for a in scored_articles if a.get("category") == category]

        # If high articles haven't had Step 1 run yet, run it now.
        needs_step1 = [
            a for a in high_pool
            if a.get("page2_final_score") is None
            or a.get("managerial_implication") is None
        ]
        if needs_step1:
            _, errors, cost = _enrich_with_step1(needs_step1, company_key)
            all_errors.extend(errors)
            total_cost += cost

        # Refresh page2_final_score on entries that may have had only
        # final_score (Stage 3) before but no Step 1.
        pick = _pick_best_above_threshold(high_pool, threshold)
        if pick is not None:
            selections[company_key] = CompanySelection(
                company_key=company_key, article=pick,
                page2_final_score=pick["page2_final_score"],
                morning_question=None, stage_used="high",
                threshold_passed=True, fallback_reason=None,
            )
            continue

        # ---------------- Stage 2 (medium) ---------------------------------
        medium_pool: list[dict] = []
        if fetcher_fn:
            try:
                medium_pool = list(fetcher_fn(category=category, priority="medium"))
            except Exception as e:
                all_errors.append(EvaluationError(
                    stage="select", article_id="<fetch>", url=None,
                    error_type=f"fetcher_error_medium: {type(e).__name__}",
                    raw_response_excerpt=llm.redact_key(str(e))[:200],
                    occurred_at=_now_iso(),
                ))
        for art in medium_pool:
            _attach_category(art, registry)
        if medium_pool:
            _, errors, cost = _enrich_with_step1(medium_pool, company_key)
            all_errors.extend(errors)
            total_cost += cost
        pick = _pick_best_above_threshold(medium_pool, threshold)
        if pick is not None:
            selections[company_key] = CompanySelection(
                company_key=company_key, article=pick,
                page2_final_score=pick["page2_final_score"],
                morning_question=None, stage_used="medium",
                threshold_passed=True,
                fallback_reason=(
                    f"High Priority で page2_final_score >= {threshold} なし、"
                    "Medium まで広げて選定"
                ),
            )
            continue

        # ---------------- Stage 3 (reference) ------------------------------
        ref_pool: list[dict] = []
        if fetcher_fn:
            try:
                ref_pool = list(fetcher_fn(category=category, priority="reference"))
            except Exception as e:
                all_errors.append(EvaluationError(
                    stage="select", article_id="<fetch>", url=None,
                    error_type=f"fetcher_error_reference: {type(e).__name__}",
                    raw_response_excerpt=llm.redact_key(str(e))[:200],
                    occurred_at=_now_iso(),
                ))
        for art in ref_pool:
            _attach_category(art, registry)
        if ref_pool:
            _, errors, cost = _enrich_with_step1(ref_pool, company_key)
            all_errors.extend(errors)
            total_cost += cost
        pick = _pick_best_above_threshold(ref_pool, threshold)
        if pick is not None:
            selections[company_key] = CompanySelection(
                company_key=company_key, article=pick,
                page2_final_score=pick["page2_final_score"],
                morning_question=None, stage_used="reference",
                threshold_passed=True,
                fallback_reason=(
                    f"High/Medium で page2_final_score >= {threshold} なし、"
                    "Reference まで広げて選定"
                ),
            )
            continue

        # ---------------- Stage 4 (cross-industry) -------------------------
        # business.md + geopolitics.md の High + Medium まで広げて取得し、
        # 各社のキーワード pre-filter で絞ってから Step 1 評価する。
        # pre-filter は Step 1 LLM コスト抑制と Web-Repo のような構造的問題を
        # 持つ社の救済を兼ねる。
        cross_raw: list[dict] = []
        if fetcher_fn:
            for cross_cat in ("business", "geopolitics"):
                for cross_pri in CROSS_INDUSTRY_PRIORITIES:
                    try:
                        arts = list(fetcher_fn(category=cross_cat, priority=cross_pri))
                        cross_raw.extend(arts)
                    except Exception as e:
                        all_errors.append(EvaluationError(
                            stage="select", article_id="<fetch>", url=None,
                            error_type=(
                                f"fetcher_error_cross_{cross_cat}_{cross_pri}: "
                                f"{type(e).__name__}"
                            ),
                            raw_response_excerpt=llm.redact_key(str(e))[:200],
                            occurred_at=_now_iso(),
                        ))
        for art in cross_raw:
            _attach_category(art, registry)

        # Pre-filter by company-specific keywords before Step 1 evaluation.
        cross_pool = _cross_industry_filter(cross_raw, company_key)
        # De-duplicate by URL within the cross pool (business High/Medium と
        # geopolitics High/Medium で同記事が重複しうる)
        seen_urls: set[str] = set()
        cross_pool_unique: list[dict] = []
        for art in cross_pool:
            url = art.get("url")
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            cross_pool_unique.append(art)
        cross_pool = cross_pool_unique

        if cross_pool:
            _, errors, cost = _enrich_with_step1(cross_pool, company_key)
            all_errors.extend(errors)
            total_cost += cost
        pick = _pick_best_above_threshold(cross_pool, threshold)
        if pick is not None:
            keywords_hit_count = sum(
                1 for k in _cross_industry_keywords(company_key)
                if k in (pick.get("title", "") + " " + pick.get("description", ""))
            )
            selections[company_key] = CompanySelection(
                company_key=company_key, article=pick,
                page2_final_score=pick["page2_final_score"],
                morning_question=None, stage_used="cross_industry",
                threshold_passed=True,
                fallback_reason=(
                    f"companies.md 全段階で該当なし、business + geopolitics の "
                    f"High/Medium {len(cross_raw)}件 → keyword pre-filter "
                    f"{len(cross_pool)}件 → Step 1 評価で選定 "
                    f"（hit kw count: {keywords_hit_count}, threshold {threshold}）"
                ),
            )
            continue

        # ---------------- Stage 5 (none) -----------------------------------
        selections[company_key] = CompanySelection(
            company_key=company_key, article=None,
            page2_final_score=None, morning_question=None,
            stage_used="none", threshold_passed=False,
            fallback_reason="全5段階で該当なし",
        )

    return selections, all_errors, total_cost


# ---------------------------------------------------------------------------
# Step 2: 「今朝の問い」生成
# ---------------------------------------------------------------------------

def _parse_step2_response(raw_text: str) -> tuple[dict | None, str | None]:
    if not raw_text:
        return None, "empty_response"
    text = _FENCE_RE.sub("", raw_text).strip()
    if not text.startswith("{"):
        idx = text.find("{")
        if idx < 0:
            return None, "no_json_object_found"
        text = text[idx:]
    try:
        return json.loads(text), None
    except json.JSONDecodeError as e:
        return None, f"json_decode_error: {e.msg}"


def generate_morning_question(
    article: dict,
    company_key: str,
    *,
    model: str = DEFAULT_MODEL,
) -> tuple[str, list[EvaluationError], float]:
    """Run Step 2 for a single article. Returns (question, errors, cost_usd)."""
    if company_key not in COMPANY_KEYS:
        raise ValueError(f"unknown company_key {company_key!r}")

    system_prompt = _build_step2_system(company_key)
    user_msg = _build_step2_user_message(article)
    errors: list[EvaluationError] = []
    total_cost = 0.0
    last_response: llm.ClaudeResponse | None = None
    raw_excerpt = ""

    parsed: dict | None = None
    parse_err: str | None = None
    for attempt in range(2):
        if attempt == 0:
            attempt_user = user_msg
        else:
            nudge = (
                "\n\n前回の応答は JSON として解析できませんでした。"
                "コードフェンス・前置き・後置きをすべて省き、JSON 単体だけを返答してください。"
                "morning_question フィールドに 40〜80字の問いを1つ含めてください。"
            )
            attempt_user = user_msg + nudge

        last_response = llm.call_claude_with_retry(
            system=system_prompt,
            user=attempt_user,
            model=model,
            max_tokens=DEFAULT_MAX_TOKENS_STEP2,
            cache_system=True,
        )
        total_cost += last_response.cost_usd
        raw_excerpt = llm.redact_key((last_response.text or "")[:400])
        parsed, parse_err = _parse_step2_response(last_response.text)
        if parsed is not None:
            q = parsed.get("morning_question")
            if isinstance(q, str) and q.strip():
                break
            parse_err = "missing_or_empty_morning_question"
            parsed = None

    article_url = article.get("url")
    if parsed is None or not isinstance(parsed.get("morning_question"), str):
        errors.append(EvaluationError(
            stage="step2", article_id="<single>", url=article_url,
            error_type=parse_err or "non_json",
            raw_response_excerpt=raw_excerpt,
            occurred_at=_now_iso(),
        ))
        return FALLBACK_QUESTION, errors, total_cost

    question = parsed["morning_question"].strip()
    qlen = len(question)
    if qlen < 30 or qlen > 120:
        errors.append(EvaluationError(
            stage="step2", article_id="<single>", url=article_url,
            error_type=f"length_out_of_band:{qlen}",
            raw_response_excerpt=question[:200],
            occurred_at=_now_iso(),
        ))
    return question, errors, total_cost


# ---------------------------------------------------------------------------
# Default fetcher (uses scripts.fetch.run + Stage 1/2/3)
# ---------------------------------------------------------------------------

def default_fetcher(
    *,
    name_substring: str | None = None,
    category: str | None = None,
    priority: str | None = None,
    limit: int = 8,
    no_dedupe: bool = True,
) -> list[dict]:
    """Fetch + Stage 1 → Stage 2 → Stage 3 → return scored article dicts.

    The returned dicts include all rendering fields (title/description/...)
    and Stage 3's ``final_score``. category is attached via SourceRegistry.
    """
    from ..fetch import run as fetch_run

    summary = fetch_run(
        category=category,
        priority=priority,
        name_substring=name_substring,
        limit=limit,
        no_dedupe=no_dedupe,
        write_log=False,
    )
    raw_articles = summary.get("articles", [])
    if not raw_articles:
        return []

    # Convert Article objects → Stage 1 input dicts.
    pipeline_dicts: list[dict] = []
    for a in raw_articles:
        body = "\n".join(a.body_paragraphs) if a.body_paragraphs else ""
        pipeline_dicts.append({
            "url": a.link,
            "title": a.title,
            "description": _strip_html_simple(a.description),
            "body": _strip_html_simple(body),
            "source_name": a.source_name,
            "source_url": None,
            "pub_date": a.pub_date.isoformat() if a.pub_date else None,
        })

    s1_out = run_stage1(pipeline_dicts)
    surviving = [x for x in s1_out if not x.get("is_excluded")]
    if not surviving:
        return []

    s2 = run_stage2(surviving)
    integrate_scores(s2.evaluations_by_url)

    by_url = s2.evaluations_by_url
    registry = _get_registry()
    scored: list[dict] = []
    for art in surviving:
        url = art.get("url")
        if url and url in by_url:
            art.update(by_url[url])
            _attach_category(art, registry)
            scored.append(art)
    return scored


_HTML_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")


def _strip_html_simple(text: str | None) -> str:
    if not text:
        return ""
    no_tags = _HTML_TAG_RE.sub(" ", text)
    no_entities = (
        no_tags.replace("&nbsp;", " ").replace("&amp;", "&")
        .replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"')
    )
    return _WHITESPACE_RE.sub(" ", no_entities).strip()


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def run_page2_pipeline(
    scored_articles: list[dict],
    *,
    fetcher_fn: FetcherFn | None = None,
    write_log: bool = True,
    today: date | None = None,
    threshold: float = DEFAULT_THRESHOLD,
    model: str = DEFAULT_MODEL,
) -> Page2Result:
    """End-to-end Page 2 pipeline: select 3 articles + generate 3 questions."""
    if today is None:
        today = date.today()
    result = Page2Result(threshold=threshold, today=today)

    # Pre-flight cap check.
    cap = llm_usage.check_caps(today)
    if not cap.ok:
        print(
            f"[page2] daily cap reached: {cap.reason}", file=sys.stderr,
        )
        for k in COMPANY_KEYS:
            result.selections[k] = CompanySelection(
                company_key=k, article=None, page2_final_score=None,
                morning_question=None, stage_used="none",
                threshold_passed=False,
                fallback_reason=f"日次キャップ抵触: {cap.reason}",
            )
        return result

    # Selection (Step 1 内蔵 + 5段階フォールバック).
    selections, sel_errors, sel_cost = select_page2_articles(
        scored_articles, fetcher_fn=fetcher_fn, threshold=threshold,
    )
    result.errors.extend(sel_errors)
    result.cost_usd += sel_cost

    # Step 2 for each selected article.
    for company_key, sel in selections.items():
        if sel.article is None:
            continue
        try:
            question, q_errors, q_cost = generate_morning_question(
                sel.article, company_key, model=model,
            )
        except llm.CapExceededError as e:
            result.errors.append(EvaluationError(
                stage="step2", article_id="<single>",
                url=sel.article.get("url"),
                error_type="cap_exceeded",
                raw_response_excerpt=llm.redact_key(str(e))[:200],
                occurred_at=_now_iso(),
            ))
            sel.morning_question = FALLBACK_QUESTION
            continue
        result.errors.extend(q_errors)
        result.cost_usd = round(result.cost_usd + q_cost, 6)
        sel.morning_question = question

    result.selections = selections

    if write_log:
        write_page2_log(result)

    return result


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def _page2_log_path(d: date | None = None) -> Path:
    return LOG_DIR / f"page2_scores_{(d or date.today()).isoformat()}.json"


def write_page2_log(result: Page2Result) -> Path:
    today = result.today or date.today()
    path = _page2_log_path(today)
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    evaluations: dict[str, dict] = {}
    selection_log: dict[str, dict] = {}

    for k in COMPANY_KEYS:
        sel = result.selections.get(k)
        if sel is None:
            continue
        display = SHORT_TO_DISPLAY[k]
        if sel.article is None:
            selection_log[display] = {
                "stage_used": sel.stage_used,
                "url": None,
                "fallback_reason": sel.fallback_reason,
                "company_key": k,
            }
            continue

        url = sel.article.get("url")
        if url:
            evaluations[url] = {
                "company_category": sel.article.get("category"),
                "company_key": k,
                "managerial_implication": sel.article.get("managerial_implication"),
                "regulatory_signal": sel.article.get("regulatory_signal"),
                "managerial_implication_reason": sel.article.get(
                    "managerial_implication_reason"
                ),
                "regulatory_signal_reason": sel.article.get(
                    "regulatory_signal_reason"
                ),
                "stage3_final_score": sel.article.get("final_score"),
                "page2_final_score": sel.page2_final_score,
                "morning_question": sel.morning_question,
                "selected_for_page2": True,
                "stage_used": sel.stage_used,
                "threshold_passed": sel.threshold_passed,
                "evaluated_at": _now_iso(),
                "model": DEFAULT_MODEL,
                "title": sel.article.get("title"),
                "source_name": sel.article.get("source_name"),
            }
        selection_log[display] = {
            "stage_used": sel.stage_used,
            "url": url,
            "fallback_reason": sel.fallback_reason,
            "page2_final_score": sel.page2_final_score,
            "company_key": k,
        }

    data = {
        "date": today.isoformat(),
        "threshold": result.threshold,
        "evaluations": evaluations,
        "selection_log": selection_log,
        "evaluation_errors": [
            {
                "stage": e.stage,
                "article_id": e.article_id,
                "url": e.url,
                "error_type": e.error_type,
                "raw_response_excerpt": e.raw_response_excerpt,
                "occurred_at": e.occurred_at,
            }
            for e in result.errors
        ],
        "cost_usd": round(result.cost_usd, 6),
    }
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _print_summary(result: Page2Result) -> None:
    print()
    print("=== Page 2 results ===")
    print(f"  date:      {result.today}")
    print(f"  threshold: {result.threshold}")
    print(f"  cost:      ${result.cost_usd:.4f}")
    print(f"  errors:    {len(result.errors)}")
    print()
    for k in COMPANY_KEYS:
        sel = result.selections.get(k)
        if sel is None:
            continue
        display = SHORT_TO_DISPLAY[k]
        if sel.article is None:
            print(f"  [{display}]  stage={sel.stage_used}  → no article today")
            print(f"      reason: {sel.fallback_reason}")
            continue
        print(
            f"  [{display}]  stage={sel.stage_used}  "
            f"score={sel.page2_final_score}  url={sel.article.get('url','')[:60]}"
        )
        if sel.fallback_reason:
            print(f"      fallback: {sel.fallback_reason}")
        print(f"      title:    {sel.article.get('title','')[:80]}")
        print(f"      source:   {sel.article.get('source_name','')}")
        print(f"      問い:     {sel.morning_question}")


def _gather_initial_scored(today: date | None) -> list[dict]:
    """Fresh fetch from companies.md High Priority, Stage 1→2→3, attach category."""
    print(
        f"[page2] fetching companies.md High Priority sources …",
        file=sys.stderr,
    )
    arts = default_fetcher(
        category="companies:", priority="high", limit=8, no_dedupe=True,
    )
    print(f"[page2]   got {len(arts)} scored articles", file=sys.stderr)
    by_cat = Counter(a.get("category", "?") for a in arts)
    for cat, n in by_cat.most_common():
        print(f"[page2]     {cat}: {n}", file=sys.stderr)
    return arts


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="page2",
        description="Phase 2 第2面（社長の朝会）パイプライン",
    )
    p.add_argument("--date", help="ISO date (YYYY-MM-DD), defaults to today")
    p.add_argument(
        "--threshold", type=float, default=DEFAULT_THRESHOLD,
        help=f"page2_final_score の採用しきい値（default {DEFAULT_THRESHOLD}）",
    )
    p.add_argument(
        "--dry-run", action="store_true",
        help="logs/page2_scores_*.json への書込をスキップ、結果は stdout のみ",
    )
    args = p.parse_args(argv)

    if args.date:
        try:
            target = date.fromisoformat(args.date)
        except ValueError:
            print(f"invalid --date {args.date!r}", file=sys.stderr)
            return 1
    else:
        target = date.today()

    cap = llm_usage.check_caps(target)
    if not cap.ok:
        print(f"[page2] daily cap reached: {cap.reason}", file=sys.stderr)
        return 2

    initial = _gather_initial_scored(target)

    result = run_page2_pipeline(
        initial,
        fetcher_fn=default_fetcher,
        write_log=not args.dry_run,
        today=target,
        threshold=args.threshold,
    )

    _print_summary(result)
    if args.dry_run:
        print()
        print("  (dry-run; logs/page2_scores_*.json は書込まれていません)")
    else:
        print()
        print(f"  log: {_page2_log_path(target)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
