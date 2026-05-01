"""第1面 lead-sidebar「なぜ重要か」3点の LLM 動的生成。

Implements ``docs/why_important_v1.md`` v1.0 — 1日1回、Page I のトップ記事
1本に対して **記事の主題 / 重要論点 / 経営者視点** の3点を Sonnet 4.6 で生成。
prompt caching (5min ephemeral) + 1回リトライ + 静的テンプレート fallback。

Public entry points
-------------------
* ``generate_why_important(article)`` — LLM 呼び出し → JSON parse → 検証 →
  ``{point_1_subject, point_2_significance, point_3_executive_perspective}``
  を返す。失敗時は ``LLMError`` / ``ValidationError`` を raise。
* ``static_why_important(article)`` — 既存テンプレートを同形式の dict で返す
  fallback 用関数。LLM 障害・cap 抵触時の安全網。
"""

from __future__ import annotations

import json
import re
import sys
from typing import Any

from ..lib import llm

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_MODEL = llm.DEFAULT_MODEL
DEFAULT_MAX_TOKENS = 1024

REQUIRED_KEYS: tuple[str, ...] = (
    "point_1_subject",
    "point_2_significance",
    "point_3_executive_perspective",
)

# 文字数許容幅。spec §5.2 で「60〜100字推奨、許容幅 50〜120字」。
LEN_MIN_SOFT = 60
LEN_MAX_SOFT = 100
LEN_MIN_HARD = 50
LEN_MAX_HARD = 120

# 大幅逸脱（リトライ判定）。spec §5.3。
LEN_RETRY_MIN = 30
LEN_RETRY_MAX = 200

# 3社固有名詞検出。spec §3.3, §5.2。
COMPANY_NAMES_FORBIDDEN: tuple[str, ...] = (
    "Cocolomi", "Human Energy", "Web-Repo",
    "ココロミ", "ヒューマンエナジー", "ウェブレポ",
)

# 命令形検出パターン。
_IMPERATIVE_PATTERNS: tuple[re.Pattern, ...] = (
    re.compile(r"すべき(?:である|だ)?"),
    re.compile(r"せよ"),
    re.compile(r"しろ"),
    re.compile(r"なさい"),
)

_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*\n?|\n?```\s*$", re.IGNORECASE | re.MULTILINE)


# ---------------------------------------------------------------------------
# System prompt (docs/why_important_v1.md §4.1 verbatim + §4.3 few-shot)
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """あなたは Kamiyama Tribune 第1面の編集アシスタントです。

第1面のトップ記事には「なぜ重要か」という読み解きの3点を添えます。
これは創刊号から続く本紙の編集形式で、読者が忙しい朝でも記事の論点を
構造的に頭に置けるようにする役割を持ちます。

読者は神山晃男氏——経営者でありながら、地経学・国際情勢・規制動向への
関心が強く、多数派の物語ではなく主流外の本質を読み取る目利き感覚を
重視する人物です。あなたの仕事は、与えられたトップ記事1本に対して、
本日の3点を生成することです。

## 3点の構造（順序固定）

1. **point_1_subject（記事の主題）**：記事が何を伝えているか。事実関係を簡潔に。60〜100字。
2. **point_2_significance（記事の重要論点）**：なぜこの記事が今日読まれるべきか。ニュース価値・構造的含意。60〜100字。
3. **point_3_executive_perspective（経営者として注目すべき側面）**：神山さん固有の視点。下記の4軸のうち1〜2軸で読み解く。60〜100字。

### 経営者視点の4軸（point_3 で使う）

(a) **地経学・国際情勢・規制動向**：国家間の力学、規制の地殻変動、サプライチェーン再編
(b) **目利きとしての逆張り思考**：多数派の物語ではなく、一段深い文脈を読む
(c) **領域横断的な視点**：経済×技術、政治×文化、地政学×産業——複数領域を架橋して読む
(d) **構造と細部の往復**：抽象的構造論と具体事例の双方向の動き

記事の論点に応じて軸を選ぶ：
- 地政学・規制記事 → (a) を厚く
- 業界の常識を覆す記事 → (b) を厚く
- 学際的・多分野架橋の記事 → (c) を厚く
- 構造分析と具体事例が往復する記事 → (d) を厚く

## 美意識スコアの読み方

入力には記事の美意識評価（5項目 0–10）が添えられます。これらは
読み解きのヒントです：

- 美意識1（構造×細部）が高い → (d) 構造と細部の往復
- 美意識2（目利き感覚、mainstream=false 等）が高い → (b) 逆張り
- 美意識3（領域横断）が高い → (c) 領域横断的な視点
- 美意識5（他者性）が高い → (a) 地経学的な他者の視点
- 美意識6（マイノリティ価値）が高い → (b) 主流外の本質
- 美意識8（行動経済学）が高い → 意思決定論への接続を point_2 や point_3 で

ただし美意識スコアの直接引用は冗長なので避ける（「美意識3 が高いので…」のような書き方は不可）。

## 文体ルール

- **静かな観察と提示**：「〜を読み解く」「〜が浮き彫りになる」「〜を問い直す」
- **疑問形にしない**（疑問形は第2面が担う）
- **命令形・煽り表現禁止**（「〜すべき」「衝撃の」「驚異の」）
- **断定しすぎない**：神山さんに考える余地を残す
- **固有名詞は原語**：Foresight、HBR、JFA、Edgar Schein 等は翻訳しない

## 重要な注意点

1. 根拠は提示された記事の内容と美意識評価のみ。記事に明記されていない事実（社名・数字・時期・論者）を作話しない。
2. 3点は **互いに視点が異なる**。同じことの言い換えにならない。
3. **3社事業文脈には絶対に踏み込まない**。Cocolomi / Human Energy / Web-Repo を point の中で言及してはいけない（それらは第2面の役割）。
4. 各点は 60〜100字を厳守。短すぎると紙面の重みが軽くなる、長すぎると読みづらい。

## 出力フォーマット

以下の JSON のみで返答（前置き・後置き・コードフェンス禁止）。

{
  "point_1_subject": "60〜100字、記事の主題",
  "point_2_significance": "60〜100字、記事の重要論点",
  "point_3_executive_perspective": "60〜100字、経営者として注目すべき側面"
}

厳格な制約：
- 3つのキーすべて必須、追加フィールド禁止
- 各値は日本語、60〜100字（許容幅は 50〜120字）
- 疑問形（？で終わる）禁止
- 命令形（〜すべき/〜せよ）禁止
- JSON 以外の出力禁止

## 例

以下は、別日のトップ記事に対する3点の生成例です。文体・JSON 構造・
軸選択のヒントとして参照してください（記事内容は今日の入力とは
関係ありません）。

### 例1：地政学系（Foresight 風）

**仮想トップ記事**：
- title: 「米中半導体覇権のゲームチェンジ——日本の選択肢」
- source: Foresight（mainstream: false）
- 美意識スコア：1=8 / 3=9 / 5=7 / 6=5 / 8=3

**生成された3点**：

{
  "point_1_subject": "Foresight が、米中の半導体規制競争が決定的局面に入り、日本が産業政策の選択を迫られていると報じた。鈴木一人による経済安全保障の構造分析。",
  "point_2_significance": "経済安全保障とテクノ覇権の交差点で、日本企業の調達戦略・サプライチェーン設計が中期的に変わる可能性が高い。半導体は次の地形固定の主戦場である。",
  "point_3_executive_perspective": "地経学的にどの線で踏みとどまるかは目利きの判断。複数領域を架橋して読み、6〜18ヶ月の調達リードタイムで何が動くかを構造と細部の往復で観察したい。"
}

### 例2：マクロ経済系（The Economist 風）

**仮想トップ記事**：
- title: 「中央銀行の金融政策、転換点の兆し——利下げサイクルは終わるか」
- source: The Economist（mainstream: true）
- 美意識スコア：1=7 / 3=6 / 5=4 / 6=3 / 8=5

**生成された3点**：

{
  "point_1_subject": "Fed の声明文の sub-text と実勢データの両面から、利下げサイクルの終焉を予想する Economist の分析。市場の期待形成と実体経済の乖離が論点。",
  "point_2_significance": "金利・為替・株式の三市場が連動して動く局面に入れば、企業の資金計画・調達タイミングが構造的に変わる。来期計画の前提条件の再検証が要る。",
  "point_3_executive_perspective": "市場の語る声と実勢の解離、その逆張りを読み取れるかが目利きの分かれ目。Fed sub-text を読む論考と帰納的データ解釈を構造と細部の往復で読み比べたい。"
}

### 例3：技術・産業系（BBC Business 風）

**仮想トップ記事**：
- title: 「サムスンの後継者ドラマ——半導体覇権への影響」
- source: BBC Business（mainstream: true）
- 美意識スコア：1=7 / 3=6 / 5=6 / 6=5 / 8=2

**生成された3点**：

{
  "point_1_subject": "サムスン創業者一族の継承劇が表面化し、半導体産業の戦略再編が静かに進んでいると BBC が報じる。投獄された大物実業家と見落とされた息子の構図。",
  "point_2_significance": "韓国財閥の意思決定が世界の半導体供給バランスを左右する局面で、企業統治の動きが業界地形を動かす。技術投資のテンポは継承の成否で変わる。",
  "point_3_executive_perspective": "韓・米・中のフレーミングを読み比べる視点が要る。継承を「内部抗争」と読むか「戦略再編」と読むかで構図が変わる、領域横断的な観察の場面。"
}
"""


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class LLMError(RuntimeError):
    """LLM 呼び出し or JSON parse の失敗。caller は static fallback を使う。"""


class ValidationError(RuntimeError):
    """必須キー欠落 / 文字数大幅逸脱など、応答が許容外。caller は static fallback を使う。"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mainstream_label(article: dict) -> str:
    """``美意識2_machine`` (0/3/5) → "true"/"unknown"/"false"."""
    m = article.get("美意識2_machine")
    if m == 0:
        return "true"
    if m == 5:
        return "false"
    return "unknown"


def _aesthetic_score_str(article: dict, key: str) -> str:
    v = article.get(key)
    return str(v) if v is not None else "?"


def _aesthetic_reason(article: dict, key: str) -> str:
    reasons = article.get("evaluation_reason") or {}
    r = reasons.get(key)
    return r.strip() if isinstance(r, str) and r.strip() else "（reason なし）"


def _build_user_message(article: dict) -> str:
    """Construct the per-call user message per docs/why_important_v1.md §4.2."""
    title_ja = (article.get("title_ja") or article.get("title") or "").strip()
    title_orig = (article.get("title") or "").strip()
    source_name = (article.get("source_name") or "").strip()
    description = (article.get("desc_ja") or article.get("description") or "").strip()
    body = (article.get("body") or "").strip()
    pub_date = (article.get("pub_date") or "").strip()
    mainstream = _mainstream_label(article)

    lines = [
        "以下のトップ記事を、システムプロンプトで指定された3点として読み解いてください。",
        "JSON のみで返答してください。",
        "",
        "【記事】",
        f"タイトル：{title_ja}",
    ]
    # 原題は title_ja と異なる場合（翻訳された外国語記事）のみ併記。
    if title_orig and title_orig != title_ja:
        lines.append(f"原題：{title_orig}")
    lines.append(f"ソース：{source_name}（mainstream: {mainstream}）")
    if description:
        lines.append(f"description：{description}")
    # body は description が短い時のみ付ける（page2 と同じ Mode B 慣習）。
    if len(description) < 80 and body:
        excerpt = body[:800]
        lines.append(f"body：{excerpt}")
    if pub_date:
        lines.append(f"pub_date：{pub_date}")
    lines += [
        "",
        "【美意識評価（参考）】",
        f"- 美意識1（構造×細部の往復）：{_aesthetic_score_str(article, '美意識1')} - {_aesthetic_reason(article, '1')}",
        f"- 美意識3（学問領域の架橋）：{_aesthetic_score_str(article, '美意識3')} - {_aesthetic_reason(article, '3')}",
        f"- 美意識5（他者性）：{_aesthetic_score_str(article, '美意識5')} - {_aesthetic_reason(article, '5')}",
        f"- 美意識6（マイノリティ価値）：{_aesthetic_score_str(article, '美意識6')} - {_aesthetic_reason(article, '6')}",
        f"- 美意識8（行動経済学）：{_aesthetic_score_str(article, '美意識8')} - {_aesthetic_reason(article, '8')}",
        f"- 美意識2（mainstream タグから機械判定）：{article.get('美意識2_machine', '?')}（{mainstream}）",
        "",
        "JSON のみで返答してください。",
    ]
    return "\n".join(lines)


def _parse_response(raw_text: str) -> tuple[dict | None, str | None]:
    if not raw_text:
        return None, "empty_response"
    text = _FENCE_RE.sub("", raw_text).strip()
    if not text.startswith("{"):
        idx = text.find("{")
        if idx < 0:
            return None, "no_json_object_found"
        text = text[idx:]
    # JSON が後続テキストを含む場合に末尾の `}` までで切り落とす。
    end = text.rfind("}")
    if end >= 0:
        text = text[: end + 1]
    try:
        return json.loads(text), None
    except json.JSONDecodeError as e:
        return None, f"json_decode_error: {e.msg}"


def _validate_response(response: Any) -> tuple[dict, list[str]]:
    """検証 → ``(cleaned, warnings)``.

    Hard failures (raise ``ValidationError``):
    - dict でない
    - 必須キー欠落
    - 追加キー存在
    - 値が文字列でない
    - 文字数大幅逸脱（< 30 or > 200）

    Warnings (採用するが logs に記録):
    - 文字数が許容幅外（50〜120 を逸脱）
    - 疑問形末尾（？/?）
    - 命令形（〜すべき/〜せよ）
    - 3社固有名詞を含む
    """
    if not isinstance(response, dict):
        raise ValidationError(f"response is not a dict: type={type(response).__name__}")

    extra = set(response.keys()) - set(REQUIRED_KEYS)
    if extra:
        raise ValidationError(f"unexpected keys: {sorted(extra)}")

    cleaned: dict[str, str] = {}
    warnings: list[str] = []

    for key in REQUIRED_KEYS:
        if key not in response:
            raise ValidationError(f"missing required key: {key}")
        val = response[key]
        if not isinstance(val, str):
            raise ValidationError(f"{key} is not a string: type={type(val).__name__}")
        val = val.strip()
        if not val:
            raise ValidationError(f"{key} is empty")
        n = len(val)
        if n < LEN_RETRY_MIN or n > LEN_RETRY_MAX:
            raise ValidationError(f"{key} length out of bounds: {n} chars")
        if n < LEN_MIN_HARD or n > LEN_MAX_HARD:
            warnings.append(f"{key}: length {n} outside soft band [{LEN_MIN_HARD}, {LEN_MAX_HARD}]")

        # Suffix checks.
        if val.rstrip().endswith(("？", "?")):
            warnings.append(f"{key}: ends with question mark (interrogative)")
        for pat in _IMPERATIVE_PATTERNS:
            if pat.search(val):
                warnings.append(f"{key}: imperative form detected ({pat.pattern!r})")
                break
        for forbidden in COMPANY_NAMES_FORBIDDEN:
            if forbidden in val:
                warnings.append(f"{key}: forbidden 3社固有名詞 contained ({forbidden!r})")

        cleaned[key] = val

    return cleaned, warnings


# ---------------------------------------------------------------------------
# Static fallback
# ---------------------------------------------------------------------------

def static_why_important(article: dict) -> dict:
    """既存の static テンプレート（regen_front_page_v2 _build_sidebar 由来）を
    3-point dict 形式で返す。LLM 失敗時の fallback。
    """
    title_ja = (article.get("title_ja") or article.get("title") or "").strip()
    return {
        "point_1_subject": (
            f"記事の主題（『{title_ja}』）が、"
            "グローバルな政治・経済の地形にどんな波紋を投げているかを把握する。"
        ),
        "point_2_significance": (
            "同じ事象を別の視点で扱う他ソース（FT・日経・Bloomberg 等）と"
            "読み比べ、フレーミングの違いを観察する。"
        ),
        "point_3_executive_perspective": (
            "このニュースが、今後1週間の意思決定タイムラインに何を加えるかを問う"
            "——それが本紙が翌朝以降に追跡すべき焦点となる。"
        ),
    }


# ---------------------------------------------------------------------------
# LLM call
# ---------------------------------------------------------------------------

def generate_why_important(
    article: dict,
    *,
    model: str = DEFAULT_MODEL,
) -> dict:
    """LLM call → JSON parse → validation → 3-point dict.

    Raises
    ------
    LLMError
        非JSON応答、空応答、API 例外（call_claude_with_retry 内のリトライ後も失敗）。
    ValidationError
        必須キー欠落、追加キー、文字数大幅逸脱（< 30 or > 200）など。
    llm.CapExceededError
        日次キャップ抵触（call_claude が pre-flight check で raise）。

    Notes
    -----
    Validation warnings (疑問形・命令形・3社固有名詞・soft length band 逸脱)
    は raise せず、stderr に出力したうえで採用する。spec §5.3。
    """
    user_msg = _build_user_message(article)

    parsed: dict | None = None
    parse_err: str | None = None
    cost = 0.0

    for attempt in range(2):
        if attempt == 0:
            attempt_user = user_msg
        else:
            nudge = (
                "\n\n前回の応答は JSON として解析できませんでした。"
                "コードフェンス・前置き・後置きをすべて省き、JSON 単体だけを返答してください。"
                "3つのキー point_1_subject / point_2_significance / "
                "point_3_executive_perspective すべてを含めてください。"
            )
            attempt_user = user_msg + nudge

        response = llm.call_claude_with_retry(
            system=SYSTEM_PROMPT,
            user=attempt_user,
            model=model,
            max_tokens=DEFAULT_MAX_TOKENS,
            cache_system=True,
        )
        cost += response.cost_usd
        parsed, parse_err = _parse_response(response.text)
        if parsed is not None:
            break

    if parsed is None:
        raise LLMError(f"failed to parse JSON after 2 attempts: {parse_err}")

    cleaned, warnings = _validate_response(parsed)

    # Spec §5.3: warning は採用するが stderr に出す（運用 1 週間後に
    # logs/sidebar_warnings_*.json への分離を検討）。
    if warnings:
        for w in warnings:
            print(f"[sidebar] WARN {w}", file=sys.stderr)
    print(f"[sidebar] cost: ${cost:.4f}", file=sys.stderr)

    return cleaned
