"""Stage 2: LLM batch evaluation.

Stage 2 takes Stage 1's surviving articles (``is_excluded == False``),
groups them in batches of 10, and asks Claude Sonnet 4.6 to score each on
the five LLM-judged aesthetics (1, 3, 5, 6, 8) per
``docs/stage2_prompts_v1.md`` v1.1.

Output for each article: the five aesthetic scores, the five reasons, and
metadata (model, evaluated_at). Errors are captured in a parallel array
so the pipeline never silently drops articles.

Public entry points
-------------------
* ``evaluate_batch(articles)``  — score one batch (≤10 articles)
* ``run_stage2(articles, batch_size=10)`` — orchestrate batches + logging
* ``main(argv)``  — ``python3 -m scripts.selector.stage2 ...`` CLI

Logs written
------------
* ``logs/scores_YYYY-MM-DD.json``  — per-article scores + reasons (this module)
* ``logs/llm_usage_YYYY-MM-DD.json`` — token & cost (via ``lib.llm_usage``)
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from ..lib import llm, llm_usage

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_MODEL = "claude-sonnet-4-6"
DEFAULT_BATCH_SIZE = 10
DEFAULT_MAX_TOKENS = 4096

# §4.2 Mode-A vs Mode-B threshold (description char count).
MODE_A_DESC_THRESHOLD = 80
BODY_EXCERPT_LIMIT = 800

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
LOG_DIR = PROJECT_ROOT / "logs"

# Mapping from LLM-output English keys → log-side Japanese keys.
# docs/stage2_prompts_v1.md §5.3.
AESTHETIC_KEYS: tuple[tuple[str, str, str], ...] = (
    # (english_key, japanese_score_key, reason_short_key)
    ("aesthetic_1_structure_detail",     "美意識1", "1"),
    ("aesthetic_3_disciplinary_bridge",  "美意識3", "3"),
    ("aesthetic_5_otherness",            "美意識5", "5"),
    ("aesthetic_6_minority_value",       "美意識6", "6"),
    ("aesthetic_8_behavioral_economics", "美意識8", "8"),
)

# ---------------------------------------------------------------------------
# System prompt (DO NOT EDIT — sync with docs/stage2_prompts_v1.md §3 v1.1)
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """あなたは神山晃男氏のためにパーソナライズされた英字朝刊「Kamiyama Tribune」の記事選定を支援するアシスタントです。

神山氏は、複数の事業を経営しながら学術領域（現象学・認知科学・暗黙知）と幅広い趣味（読書・音楽・アウトドア・料理）を統合する読者です。主流外の本質を発掘する目利き感覚を重視し、規模・派手さ・成功談ではなく構造・深さ・他者性を価値とします。

あなたの仕事は、与えられた記事10本のそれぞれに対し、神山氏の「美意識7項目」のうち5項目（美意識1, 3, 5, 6, 8）を0–10で評価し、根拠を簡潔な日本語で添えることです。残る美意識2（目利き感覚＝主流外）と美意識4（規模より本質＝ペナルティキーワード）は機械的フィルタで処理済み、美意識7（予断なく見る）は紙面配置で実現するため、本評価には含めません。

## 各美意識の評価軸

### 美意識1：構造と細部の往復（重み18）

この記事は「構造的な議論（抽象的な枠組み・原理・理論）」と「具体的な細部（事例・現場の描写・固有名詞による具体性）」の両方を含んでいるか？片方だけの記事は低スコア。両方が往復している記事は高スコア。

スコアバンド：
- 9–10：抽象論と具体例が見事に往復している
- 6–8：両方含むが片方が薄い
- 3–5：片方しかない
- 0–2：表層的な記事

### 美意識3：学問領域・ジャンルを架橋する（重み27）

この記事は、複数の学問領域・ジャンル・分野を架橋しているか？（例：物理学×哲学、経営学×心理学、文学×政治、科学×宗教）。一つの分野内で完結する記事は低スコア。境界を越える記事は高スコア。

スコアバンド：
- 9–10：3つ以上の領域を架橋
- 6–8：2つの領域を架橋
- 3–5：架橋の気配があるが浅い
- 0–2：単一領域内で完結

### 美意識5：他者・異質なものへの開かれ（重み9）

この記事は「他者」「異質なもの」「自分と違う視点」を扱っているか？特に他者の認知・経験・世界観を理解しようとする記事は高スコア。自文化中心・自分側からの視点だけの記事は低スコア。

スコアバンド：
- 9–10：他者の世界観を内側から描く
- 6–8：他者を扱うが、観察的・距離あり
- 3–5：他者への言及はあるが浅い
- 0–2：自分側の視点のみ

### 美意識6：マイノリティ価値（重み9）

この記事は周縁・少数派・辺境の独自の価値を扱っているか？「弱者救済」ではなく、「マイノリティが持つ独自の価値の源泉」を見出す視点があるか。多数派の正当性を当然視する記事は低スコア。

スコアバンド：
- 9–10：マイノリティが主流に対して持つ独自価値を明確に提示
- 6–8：マイノリティを尊重するが、価値の言語化が弱い
- 3–5：マイノリティへの言及程度
- 0–2：多数派の論理一辺倒

### 美意識8：行動経済学の眼差し（重み10）

この記事は人間の認知バイアス・意思決定の歪み・非合理性を扱っているか？

評価ポイント：
- システム1/システム2、ヒューリスティクス、フレーミング効果、損失回避、確証バイアス等の概念を扱う記事は高スコア
- カーネマン、セイラー、アリエリー、チャルディーニ、友野典男、依田高典、大竹文雄等の論者の参照は加点
- 「合理的経済人」モデルへの懐疑、現実の人間行動の観察、組織における認知バイアスへの言及は高スコア
- 行動経済学的視点が明示的に入っていなければ高くしない

スコアバンド（目安）：
- 9–10：概念を中心軸に据え、論者を明示的に参照
- 6–8：概念または論者の明示的言及がある
- 3–5：合理的経済人モデルへの懐疑・人間の非合理性に踏み込むが、行動経済学の語彙は薄い
- 0–2：行動経済学的視点が見られない

### 美意識8の運用上の補足

美意識8は重み10（100点満点中）で、final_score への寄与が比較的小さい。行動経済学的視点がない記事も、他項目で十分なスコアを獲得できれば選定される。本項目は「ボーナス的に行動経済学を扱う記事を押し上げる」性格を持つ。

LLM評価時は、行動経済学なしの記事に低スコア（0–2）を与えることにためらわないこと。それは記事の質を否定するものではなく、他項目で十分にカバーされる。

## スコアリング共通ルール

- スコアは0–10の整数のみ。小数・範囲外を返してはいけない。
- 評価に迷う場合は控えめに（中央値3–4寄り）に倒し、reason で迷いを示唆する。
- キーワードのヒット数で機械的に決めず、記事全体の趣旨を読み取って判定する。
- ソース名・著者名・媒体の権威から推測せず、提示された記事内容のみを根拠とする。
- 5項目は独立評価。一つの美意識が高いからといって他項目を連鎖的に高くしない。
- 同一記事内で複数の美意識が同時に成立し得る（例：構造×細部の往復をしながら他者性も扱う）。

## 出力フォーマット

以下のJSONを、前置き・後置き・説明文・コードフェンス（```）を一切付けずにそのまま返答してください。

{
  "evaluations": [
    {
      "article_id": "art_001",
      "scores": {
        "aesthetic_1_structure_detail": 0–10の整数,
        "aesthetic_3_disciplinary_bridge": 0–10の整数,
        "aesthetic_5_otherness": 0–10の整数,
        "aesthetic_6_minority_value": 0–10の整数,
        "aesthetic_8_behavioral_economics": 0–10の整数
      },
      "reasons": {
        "aesthetic_1_structure_detail": "日本語で1〜2文、80字以内",
        "aesthetic_3_disciplinary_bridge": "日本語で1〜2文、80字以内",
        "aesthetic_5_otherness": "日本語で1〜2文、80字以内",
        "aesthetic_6_minority_value": "日本語で1〜2文、80字以内",
        "aesthetic_8_behavioral_economics": "日本語で1〜2文、80字以内"
      }
    }
  ]
}

厳格な制約：
- evaluations 配列の長さは入力記事数と一致させる。
- 各 article_id は入力されたIDをそのまま echo する。
- 5項目すべて必須。追加フィールド禁止。
- スコアは整数、範囲 [0, 10]。
- reason は空文字禁止。日本語、80字以内が目安。
- JSON 以外の出力は禁止（前置きの「以下が評価結果です：」、後置きの「以上です」、コードフェンスはすべて不可）。

## 重要な注意点

1. 根拠は提示された記事の内容のみ。タイトルやソース名から内容を類推しない。
2. キーワードが1つヒットしたから即高スコア、という機械的判定を避ける。記事全体の趣旨を見る。
3. 不明な点・判定に迷う点は中央寄りのスコアにし、reason でその旨を示唆する。
4. 5項目は独立評価。連鎖を避ける。
5. reason は具体的に書く。「該当する」「該当しない」のような抽象語のみは避け、記事のどの記述・論点が判定根拠かを示す。
6. 記事が英語の場合も、reason は日本語で書く。
"""


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class EvaluationError:
    """One per anomaly. Becomes a row in scores_*.json `evaluation_errors`."""

    article_id: str
    url: str | None
    error_type: str            # "non_json" / "missing_from_response" / "score_clamped" / ...
    raw_response_excerpt: str  # api-key-redacted, length-capped
    occurred_at: str           # ISO-8601 UTC


@dataclass
class BatchResult:
    """Output of one batch (≤10 articles)."""

    evaluations: list[dict]    # one per input article, in input order
    errors: list[EvaluationError] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0
    cost_usd: float = 0.0
    model: str = DEFAULT_MODEL


@dataclass
class Stage2Result:
    """Aggregate of all batches in one run."""

    evaluations_by_url: dict[str, dict] = field(default_factory=dict)
    errors: list[EvaluationError] = field(default_factory=list)
    batches_run: int = 0
    aborted: bool = False                # True if cap hit mid-run
    abort_reason: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0
    cost_usd: float = 0.0
    model: str = DEFAULT_MODEL


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _truncate_body(body: str, limit: int = BODY_EXCERPT_LIMIT) -> str:
    """Return up to ``limit`` chars of body, cut back to the nearest 句点 / newline."""
    if not body:
        return ""
    if len(body) <= limit:
        return body
    excerpt = body[:limit]
    # Prefer cutting at the last 句点 within the excerpt; fall back to newline.
    for sep in ("。", "\n", "．", "."):
        idx = excerpt.rfind(sep)
        if idx >= limit // 2:
            return excerpt[: idx + 1]
    return excerpt


def _format_article_block(article_id: str, art: dict) -> str:
    """Render one article in user-message format. Mode A vs B chosen here."""
    title = (art.get("title") or "").strip()
    source = (art.get("source_name") or "").strip()
    description = (art.get("description") or "").strip()
    body = (art.get("body") or "").strip()

    lines = [f"[{article_id}]", f"title: {title}", f"source: {source}"]
    if description:
        lines.append(f"description: {description}")
    # Mode B: description is too thin → include body excerpt.
    if len(description) < MODE_A_DESC_THRESHOLD and body:
        excerpt = _truncate_body(body)
        if excerpt:
            lines.append(f"body: {excerpt}")
    return "\n".join(lines)


def _build_user_message(articles: list[dict], ids: list[str]) -> str:
    n = len(articles)
    header = (
        f"以下の記事{n}本を、システムプロンプトで指定された5項目（美意識1, 3, 5, 6, 8）"
        "について評価してください。指定されたJSONフォーマットでのみ返答してください。\n"
    )
    blocks = "\n\n".join(
        _format_article_block(aid, art) for aid, art in zip(ids, articles)
    )
    footer = "\n\nJSON のみで返答してください。"
    return f"{header}\n{blocks}{footer}"


_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*\n?|\n?```\s*$", re.IGNORECASE | re.MULTILINE)


def _parse_response_json(raw_text: str) -> tuple[dict | None, str | None]:
    """Strip code fences and parse. Returns (data, error_message)."""
    if not raw_text:
        return None, "empty_response"
    text = _FENCE_RE.sub("", raw_text).strip()
    # If the model prefixed prose, try to locate the first '{' and parse from there.
    if not text.startswith("{"):
        idx = text.find("{")
        if idx < 0:
            return None, "no_json_object_found"
        text = text[idx:]
    try:
        return json.loads(text), None
    except json.JSONDecodeError as e:
        return None, f"json_decode_error: {e.msg}"


def _clamp_int(v: Any, lo: int = 0, hi: int = 10) -> tuple[int, bool]:
    """Convert to int, clamp to [lo, hi]. Returns (value, was_modified)."""
    try:
        x = int(round(float(v)))
    except (TypeError, ValueError):
        return 3, True   # default median per §6
    if x < lo:
        return lo, True
    if x > hi:
        return hi, True
    return x, x != v


def _fallback_eval(article_id: str, reason: str) -> dict:
    """Build an evaluation entry filled with score=3, reason='evaluation_failed'."""
    scores = {eng: 3 for eng, _, _ in AESTHETIC_KEYS}
    reasons = {eng: reason for eng, _, _ in AESTHETIC_KEYS}
    return {"article_id": article_id, "scores": scores, "reasons": reasons}


def _validate_evaluation(
    ev: dict,
    expected_id: str,
    raw_excerpt: str,
) -> tuple[dict, list[EvaluationError]]:
    """Normalize one evaluation entry. Returns (cleaned_entry, errors)."""
    errors: list[EvaluationError] = []
    if not isinstance(ev, dict):
        errors.append(EvaluationError(
            article_id=expected_id, url=None, error_type="not_an_object",
            raw_response_excerpt=raw_excerpt[:200], occurred_at=_now_iso(),
        ))
        return _fallback_eval(expected_id, "evaluation_failed"), errors

    # article_id mismatch — restore by position.
    aid = ev.get("article_id")
    if aid != expected_id:
        errors.append(EvaluationError(
            article_id=expected_id, url=None,
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

    cleaned_scores: dict[str, int] = {}
    cleaned_reasons: dict[str, str] = {}
    for eng, _jp, _short in AESTHETIC_KEYS:
        # Score
        if eng not in raw_scores:
            cleaned_scores[eng] = 3
            errors.append(EvaluationError(
                article_id=expected_id, url=None,
                error_type=f"missing_score:{eng}",
                raw_response_excerpt=raw_excerpt[:200],
                occurred_at=_now_iso(),
            ))
        else:
            v, modified = _clamp_int(raw_scores[eng])
            cleaned_scores[eng] = v
            if modified:
                errors.append(EvaluationError(
                    article_id=expected_id, url=None,
                    error_type=f"score_clamped:{eng}",
                    raw_response_excerpt=f"original={raw_scores[eng]!r}",
                    occurred_at=_now_iso(),
                ))
        # Reason
        r = raw_reasons.get(eng)
        if not isinstance(r, str) or not r.strip():
            if eng not in raw_reasons:
                cleaned_reasons[eng] = "missing_from_response"
                errors.append(EvaluationError(
                    article_id=expected_id, url=None,
                    error_type=f"missing_reason:{eng}",
                    raw_response_excerpt=raw_excerpt[:200],
                    occurred_at=_now_iso(),
                ))
            else:
                cleaned_reasons[eng] = "(no_reason_provided)"
                errors.append(EvaluationError(
                    article_id=expected_id, url=None,
                    error_type=f"empty_reason:{eng}",
                    raw_response_excerpt="", occurred_at=_now_iso(),
                ))
        else:
            cleaned_reasons[eng] = r.strip()

    cleaned = {
        "article_id": expected_id,
        "scores": cleaned_scores,
        "reasons": cleaned_reasons,
    }
    return cleaned, errors


# ---------------------------------------------------------------------------
# evaluate_batch
# ---------------------------------------------------------------------------

def evaluate_batch(
    articles: list[dict],
    *,
    model: str = DEFAULT_MODEL,
    max_tokens: int = DEFAULT_MAX_TOKENS,
) -> BatchResult:
    """Evaluate one batch of up to 10 articles.

    The caller is responsible for slicing batches; this function will accept
    1–10 articles. Article dicts must contain at least ``url``, ``title``,
    and one of ``description`` / ``body``.
    """
    if not articles:
        return BatchResult(evaluations=[], model=model)
    if len(articles) > DEFAULT_BATCH_SIZE:
        # Allow oversize batches but warn — the prompt was tuned for 10.
        print(
            f"[stage2] warning: batch size {len(articles)} exceeds {DEFAULT_BATCH_SIZE}",
            file=sys.stderr,
        )

    ids = [f"art_{i + 1:03d}" for i in range(len(articles))]
    user_msg = _build_user_message(articles, ids)

    parsed: dict | None = None
    parse_err: str | None = None
    last_response: llm.ClaudeResponse | None = None
    raw_excerpt = ""

    # Up to 2 tries: first the original message, second a sharpened "JSON only"
    # nudge if parse or array-length fails. API-level retries (5xx, rate, etc.)
    # are handled inside call_claude_with_retry.
    for attempt in range(2):
        if attempt == 0:
            attempt_user = user_msg
        else:
            nudge = (
                "\n\n前回の応答は JSON として解析できないか、evaluations 配列の "
                f"長さが {len(articles)} ではありませんでした。"
                "コードフェンス・前置き・後置きをすべて省き、JSON 単体だけを"
                "返答してください。evaluations の長さは正確に "
                f"{len(articles)} としてください。"
            )
            attempt_user = user_msg + nudge

        last_response = llm.call_claude_with_retry(
            system=SYSTEM_PROMPT,
            user=attempt_user,
            model=model,
            max_tokens=max_tokens,
            cache_system=True,
        )
        raw_excerpt = llm.redact_key((last_response.text or "")[:400])
        parsed, parse_err = _parse_response_json(last_response.text)

        if parsed is not None:
            evals = parsed.get("evaluations")
            if isinstance(evals, list) and len(evals) == len(articles):
                break
            # Length mismatch — try once more.
            parse_err = (
                f"array_length_mismatch: got {len(evals) if isinstance(evals, list) else 'non-list'}, "
                f"expected {len(articles)}"
            )
            parsed = None

    errors: list[EvaluationError] = []

    if parsed is None or not isinstance(parsed.get("evaluations"), list):
        # Both attempts failed → full fallback for the batch.
        errors.append(EvaluationError(
            article_id="<batch>", url=None,
            error_type=parse_err or "non_json",
            raw_response_excerpt=raw_excerpt,
            occurred_at=_now_iso(),
        ))
        evaluations = [_fallback_eval(aid, "evaluation_failed") for aid in ids]
    else:
        evals = parsed["evaluations"]
        # Pad / trim to expected length.
        if len(evals) < len(articles):
            errors.append(EvaluationError(
                article_id="<batch>", url=None,
                error_type=f"array_short:{len(evals)}<{len(articles)}",
                raw_response_excerpt=raw_excerpt,
                occurred_at=_now_iso(),
            ))
            evals = list(evals) + [None] * (len(articles) - len(evals))
        elif len(evals) > len(articles):
            errors.append(EvaluationError(
                article_id="<batch>", url=None,
                error_type=f"array_long:{len(evals)}>{len(articles)}",
                raw_response_excerpt=raw_excerpt,
                occurred_at=_now_iso(),
            ))
            evals = evals[: len(articles)]

        evaluations = []
        for expected_id, ev in zip(ids, evals):
            if ev is None:
                evaluations.append(_fallback_eval(expected_id, "missing_from_response"))
                errors.append(EvaluationError(
                    article_id=expected_id, url=None,
                    error_type="missing_from_response",
                    raw_response_excerpt=raw_excerpt,
                    occurred_at=_now_iso(),
                ))
                continue
            cleaned, ev_errors = _validate_evaluation(ev, expected_id, raw_excerpt)
            evaluations.append(cleaned)
            errors.extend(ev_errors)

    # Backfill URL into errors using batch ordering for downstream lookups.
    url_by_id = {aid: art.get("url") for aid, art in zip(ids, articles)}
    for e in errors:
        if e.url is None and e.article_id in url_by_id:
            e.url = url_by_id[e.article_id]

    if last_response is None:
        # Should not happen — call_claude_with_retry raises on failure.
        return BatchResult(evaluations=evaluations, errors=errors, model=model)

    return BatchResult(
        evaluations=evaluations,
        errors=errors,
        input_tokens=last_response.input_tokens,
        output_tokens=last_response.output_tokens,
        cache_creation_tokens=last_response.cache_creation_tokens,
        cache_read_tokens=last_response.cache_read_tokens,
        cost_usd=last_response.cost_usd,
        model=last_response.model,
    )


# ---------------------------------------------------------------------------
# run_stage2
# ---------------------------------------------------------------------------

def _to_log_entry(
    article: dict, evaluation: dict, *, model: str, evaluated_at: str
) -> dict:
    """Convert (Stage 1 article + Stage 2 evaluation) into a scores log row."""
    entry: dict[str, Any] = {}
    for eng, jp, _short in AESTHETIC_KEYS:
        entry[jp] = evaluation["scores"].get(eng, 3)
    entry["美意識2_machine"] = article.get("美意識2_score")
    entry["美意識4_penalty"] = article.get("美意識4_penalty", 0)
    entry["final_score"] = None
    entry["evaluation_reason"] = {
        short: evaluation["reasons"].get(eng, "")
        for eng, _jp, short in AESTHETIC_KEYS
    }
    entry["evaluated_at"] = evaluated_at
    entry["model"] = model
    return entry


def run_stage2(
    articles: list[dict],
    *,
    batch_size: int = DEFAULT_BATCH_SIZE,
    model: str = DEFAULT_MODEL,
    max_tokens: int = DEFAULT_MAX_TOKENS,
) -> Stage2Result:
    """Run Stage 2 over a list of Stage-1-passing articles."""
    result = Stage2Result(model=model)
    if not articles:
        return result

    for batch_start in range(0, len(articles), batch_size):
        batch = articles[batch_start : batch_start + batch_size]
        # Pre-flight cap check so we abort cleanly between batches.
        cap = llm_usage.check_caps()
        if not cap.ok:
            result.aborted = True
            result.abort_reason = cap.reason
            print(
                f"[stage2] aborting before batch {batch_start // batch_size + 1}: "
                f"{cap.reason}",
                file=sys.stderr,
            )
            break
        try:
            br = evaluate_batch(batch, model=model, max_tokens=max_tokens)
        except llm.CapExceededError as e:
            result.aborted = True
            result.abort_reason = str(e)
            print(f"[stage2] cap exceeded mid-run: {e}", file=sys.stderr)
            break

        result.batches_run += 1
        result.input_tokens += br.input_tokens
        result.output_tokens += br.output_tokens
        result.cache_creation_tokens += br.cache_creation_tokens
        result.cache_read_tokens += br.cache_read_tokens
        result.cost_usd = round(result.cost_usd + br.cost_usd, 6)
        result.errors.extend(br.errors)

        evaluated_at = _now_iso()
        for art, ev in zip(batch, br.evaluations):
            url = art.get("url")
            if not url:
                continue
            result.evaluations_by_url[url] = _to_log_entry(
                art, ev, model=br.model, evaluated_at=evaluated_at
            )

    write_scores_log(result)
    return result


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def _scores_log_path(d: date | None = None) -> Path:
    return LOG_DIR / f"scores_{(d or date.today()).isoformat()}.json"


def _load_scores_log(path: Path) -> dict:
    if not path.exists():
        return {
            "date": path.stem.removeprefix("scores_"),
            "evaluations": {},
            "evaluation_errors": [],
        }
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {
            "date": path.stem.removeprefix("scores_"),
            "evaluations": {},
            "evaluation_errors": [],
        }
    data.setdefault("evaluations", {})
    data.setdefault("evaluation_errors", [])
    return data


def write_scores_log(result: Stage2Result, *, today: date | None = None) -> Path:
    """Merge this run's evaluations + errors into today's scores log."""
    path = _scores_log_path(today)
    data = _load_scores_log(path)
    data["evaluations"].update(result.evaluations_by_url)
    data["evaluation_errors"].extend(
        {
            "article_id": e.article_id,
            "url": e.url,
            "error_type": e.error_type,
            "raw_response_excerpt": e.raw_response_excerpt,
            "occurred_at": e.occurred_at,
        }
        for e in result.errors
    )
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="stage2",
        description="Stage 2 LLM batch evaluation (Phase 2 Sprint 1)",
    )
    p.add_argument("--source", default="BBC Business", help="source name substring")
    p.add_argument("--category", help="category substring filter")
    p.add_argument(
        "--priority",
        choices=["high", "medium", "reference"],
        help="priority bucket filter",
    )
    p.add_argument("--limit", type=int, default=5, help="articles per source")
    p.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    p.add_argument("--model", default=DEFAULT_MODEL)
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="run Stage 1 only, print what Stage 2 would receive",
    )
    args = p.parse_args(argv)

    # Lazy import to keep stage2.py importable without anthropic when only
    # the helper functions are needed.
    from ..fetch import run as fetch_run
    from .stage1 import run_stage1

    summary = fetch_run(
        category=args.category,
        priority=args.priority,
        name_substring=args.source,
        limit=args.limit,
        no_dedupe=True,
        write_log=False,
    )
    raw_articles = summary["articles"]
    if not raw_articles:
        print("No articles fetched.", file=sys.stderr)
        return 1

    stage1_out = run_stage1(raw_articles)
    surviving = [a for a in stage1_out if not a.get("is_excluded")]
    print(
        f"[stage2] Stage 1 results: {len(stage1_out)} total, "
        f"{len(surviving)} surviving (Stage 2 input)",
        file=sys.stderr,
    )

    if args.dry_run:
        for a in surviving:
            print(f"  - {a.get('title','')[:80]}  ({a.get('source_name')})")
        return 0
    if not surviving:
        print("No surviving articles after Stage 1.", file=sys.stderr)
        return 1

    cap = llm_usage.check_caps()
    if not cap.ok:
        print(f"[stage2] daily cap reached: {cap.reason}", file=sys.stderr)
        return 2

    result = run_stage2(surviving, batch_size=args.batch_size, model=args.model)

    print()
    print("=== Stage 2 results ===")
    print(f"  batches run:       {result.batches_run}")
    print(f"  evaluations:       {len(result.evaluations_by_url)}")
    print(f"  errors:            {len(result.errors)}")
    if result.aborted:
        print(f"  aborted:           {result.abort_reason}")
    print(f"  input tokens:      {result.input_tokens}")
    print(f"  output tokens:     {result.output_tokens}")
    print(f"  cache create tk:   {result.cache_creation_tokens}")
    print(f"  cache read tk:     {result.cache_read_tokens}")
    print(f"  cost (USD):        ${result.cost_usd:.6f}")

    print()
    print("  per-article scores:")
    for url, entry in result.evaluations_by_url.items():
        scores = "/".join(
            f"{entry[jp]}" for _eng, jp, _short in AESTHETIC_KEYS
        )
        title = url[:60]
        print(f"    [1/3/5/6/8={scores}]  {title}")

    if result.errors:
        print()
        print(f"  first {min(5, len(result.errors))} errors:")
        for e in result.errors[:5]:
            print(f"    - {e.article_id} {e.error_type}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
