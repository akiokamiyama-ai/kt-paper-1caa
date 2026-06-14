"""Haiku pre-filter prompts for Stage 2 layered mode.

C85 Sub-Step 3 (Sprint 10, 2026-06-14, Phase B Step 4): 旧来の Stage 2
SYSTEM_PROMPT (~3500 tokens) を Haiku 用に圧縮した版。

設計
----

層 2 の pre-filter で **5 項目から 3 項目に圧縮**：

- **残す（Haiku でも判定可能）**:
  - 美意識 1（構造×細部、重み 18）: 抽象論と具体例の混在判定
  - 美意識 3（領域架橋、重み 27、最大）: 複数分野キーワードヒット
  - 美意識 8（行動経済学、重み 10）: 論者・概念の機械的判定

- **Sonnet に委ねる（精度不足項目）**:
  - 美意識 5（他者性、重み 9）: 文脈読解力が決定的
  - 美意識 6（マイノリティ価値、重み 9）: 「弱者救済」vs「独自価値」の区別

Haiku pre-filter は **30 点満点**（10 × 3 項目）の粗評価。閾値 K=15 + 上位
N% で Sonnet 精評価に進む。

層 1（Haiku full）も同じ 3 項目評価を使い、結果をそのまま採用ロジックに渡す
（Sonnet 評価をスキップ）。

設計レポート: ``/tmp/phase_b_step3_design.md`` セクション 2 参照。
"""

from __future__ import annotations

import json
import re


# ---------------------------------------------------------------------------
# System prompt (圧縮版、~1300 tokens 目標)
# ---------------------------------------------------------------------------

HAIKU_PREFILTER_SYSTEM_PROMPT = """あなたは英字朝刊「Kamiyama Tribune」の記事 pre-filter 担当です。神山晃男氏は複数事業を経営しながら学術領域（現象学・認知科学・暗黙知）と幅広い趣味を統合する読者で、主流外の本質を発掘する目利き感覚を重視します。

あなたの仕事は、各記事に対し神山氏の「美意識」のうち 3 項目（1, 3, 8）を 0–10 で評価し、簡潔な根拠を添えることです。残る 2 項目（美意識 5, 6）は別レイヤーで Sonnet が評価するため、本評価には含めません。

## 評価軸

### 美意識1：構造と細部の往復（重み18）

抽象的な枠組み・原理と、具体的な事例・固有名詞による細部の両方を含むか。
- 9–10: 抽象論と具体例が見事に往復
- 6–8: 両方含むが片方が薄い
- 3–5: 片方しかない
- 0–2: 表層的

### 美意識3：学問領域・ジャンルの架橋（重み27、最大）

複数の学問領域・分野を架橋しているか（例：物理学×哲学、経営×心理学）。
- 9–10: 3つ以上の領域を架橋
- 6–8: 2つの領域を架橋
- 3–5: 架橋の気配はあるが浅い
- 0–2: 単一領域内で完結

### 美意識8：行動経済学の眼差し（重み10）

認知バイアス・意思決定の歪み・非合理性を扱うか。
- 9–10: 概念を中心軸に据え、論者（カーネマン、セイラー、アリエリー、チャルディーニ、友野典男、依田高典、大竹文雄等）を明示
- 6–8: 概念または論者の明示的言及
- 3–5: 合理的経済人モデルへの懐疑はあるが語彙は薄い
- 0–2: 行動経済学的視点なし

行動経済学なしの記事に低スコア（0–2）を与えることをためらわないでください。他項目で十分カバーされます。

## スコアリングルール

- スコアは 0–10 の整数のみ
- 評価に迷うときは控えめ（中央値 3–4 寄り）
- キーワードヒット数で機械判定せず、記事全体の趣旨を読む
- 媒体の権威からの推測ではなく、提示された内容のみを根拠とする
- description が空の場合は title から推測。title が曖昧なら控えめに倒す

## 出力フォーマット

以下のJSONを、前置き・後置き・説明文・コードフェンス（```）を一切付けずにそのまま返答してください。

{
  "evaluations": [
    {
      "article_id": "art_001",
      "scores": {
        "aesthetic_1_structure_detail": 0–10の整数,
        "aesthetic_3_disciplinary_bridge": 0–10の整数,
        "aesthetic_8_behavioral_economics": 0–10の整数
      },
      "reason_short": "全体を1文・80字以内で要約"
    }
  ]
}
"""


# ---------------------------------------------------------------------------
# User template (圧縮版、article 配列を1 行ずつ展開)
# ---------------------------------------------------------------------------

HAIKU_PREFILTER_USER_TEMPLATE = """以下の {n_articles} 本の記事について、3項目（美意識1, 3, 8）を評価してください。

{article_blocks}

JSON のみ返してください。
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FENCE_RE = re.compile(
    r"^\s*```(?:json)?\s*\n?|\n?```\s*$",
    re.IGNORECASE | re.MULTILINE,
)


def parse_haiku_prefilter_response(
    raw_text: str,
) -> tuple[dict | None, str | None]:
    """Parse a Haiku pre-filter response.

    Returns
    -------
    (parsed_dict, error_message)
        On success: ``({"evaluations": [...]}, None)``.
        On failure: ``(None, "human-readable error string")``.

    緩い JSON parser: code fence を剥がしてから ``json.loads``。
    """
    if not raw_text:
        return None, "empty response"
    cleaned = _FENCE_RE.sub("", raw_text).strip()
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as e:
        return None, f"json decode error: {e}"
    if not isinstance(data, dict):
        return None, f"expected dict at root, got {type(data).__name__}"
    if "evaluations" not in data:
        return None, "missing 'evaluations' key"
    if not isinstance(data["evaluations"], list):
        return None, f"'evaluations' must be a list, got {type(data['evaluations']).__name__}"
    return data, None


def haiku_prefilter_score(
    aesthetic_1: int,
    aesthetic_3: int,
    aesthetic_8: int,
) -> int:
    """Compute the pre-filter score (0–30) from 3 aesthetic scores.

    現在は単純合計（重み無し、3 項目 × 0-10 = 0-30 点）。本値が
    ``LayerConfig.k_threshold`` を上回り、かつ上位 ``n_for_caller()`` % に入る
    と Sonnet 精評価へ進む（ハイブリッド閾値方式 = 案 C）。

    将来、重み付けを変更したい場合は本関数を差し替える。例:

        return int(aesthetic_1 * 1.8 + aesthetic_3 * 2.7 + aesthetic_8 * 1.0)

    （weight 1+3+8 = 18+27+10 = 55、フル評価との比例 55/100 倍）
    """
    return aesthetic_1 + aesthetic_3 + aesthetic_8


def estimate_prompt_tokens(prompt: str) -> int:
    """Rough token-count heuristic for sanity checking (≈ chars × 0.5 for JA mix).

    厳密な tokenizer は使わない（dependency 増を避ける）。本関数は CI で
    「prompt が 1500 tokens 以内」をゲートするための目安。
    """
    return int(len(prompt) * 0.55)  # 0.55 は日本語混じり経験則
