"""Generate the 'Concept of the Week' essay via LLM.

Input: concept dict (from concepts.yaml) + 関連概念のリスト。
Output: ``{"concept", "essay", "related", "is_fallback", "cost_usd"}``。

C158 (Sprint 13, 2026-08-12): 関連概念セクションを追加した。C155 で学術ニュース
3 本を廃止して第4面が概念 1 本だけになり分量的に寂しくなったため、
concepts.yaml のグラフ構造（``related``）を紙面に可視化する。

**コスト方針**: 関連概念の解説は本文と同じ 1 回の LLM 呼び出しで生成する
（別呼び出しにしない）。応答を「本文」と「関連概念の解説」に分割するため、
プロンプトで区切り記号を指示し、``_split_response`` でパースする。
パースに失敗した場合は応答全体を本文とみなし、関連概念は seed の 1 文目に
フォールバックする（紙面は落とさない）。

LLM failure or empty response → static fallback to the seed text. Sidebar-style
WARN logged so the issue is visible without crashing the page.
"""

from __future__ import annotations

import re
import sys

from ..lib import llm

DEFAULT_MODEL = llm.DEFAULT_MODEL
# C158: 関連概念 2-3 件の解説（各 1-2 文）が加わる分を増量。
DEFAULT_MAX_TOKENS = 2200
DEFAULT_TEMPERATURE = 0.7

# LLM 応答を本文 / 関連概念に割るための区切り。記号自体が紙面に出ないよう
# パース後に必ず除去する。マークダウン記法と紛れない文字列を選ぶ。
ESSAY_MARKER = "===本文==="
RELATED_MARKER = "===関連概念==="

SYSTEM_PROMPT = """あなたは Kamiyama Tribune 第4面 Arts & Letters の
『今日の概念』コラム執筆者です。

読者：哲学・認知科学・思想史に深い関心を持つ経営者。
専門用語は使ってよいが、初出時は短い補足を添える。
学術論文ではなく、知的な読み物として書く。
1段落で 400〜600字。前置きや結論を別段落にしない、
連続した思考の流れとして書く。

続けて、指定された関連概念それぞれについて
「今日の概念とどう繋がるか」を 1〜2 文で書く。
概念の一般的な説明ではなく、**今日の概念との関係**を書くこと。
  ・○「キャノンがベルナールの内的環境を生理学的に定式化した後継概念」
  ・×「生体が内部環境を一定に保つ働きのこと」（単なる語義説明）

【マークダウン記号の絶対禁止】★ 紙面で記号がそのまま見える事故になります
- 本文中で **太字** _斜体_ ## 見出し > 引用 - リスト 等のマークダウン記法を
  使用しない（HTML 変換されず記号がそのまま表示される）
- 強調したい語句があっても **記号** で囲まず、文章のリズムで強調する
  ・×「概念の核は **権力の流れ** である」
  ・○「概念の核は『権力の流れ』である」または「概念の核は権力の流れにある」"""


def _build_user_message(concept: dict, related: list[dict] | None = None) -> str:
    thinkers = ", ".join(concept.get("thinkers", []))
    seed = (concept.get("seed") or "").strip()
    related = related or []

    lines = [
        "以下の概念について、コラム1本分（400〜600字）で書いてください。",
        "",
        f"概念名：{concept['name_ja']}（{concept['name_en']}）",
        f"領域：{concept['domain']}",
        f"代表的思想家：{thinkers}",
        f"基本定義：{seed}",
        "",
        "執筆方針：",
        "- 概念の核を最初の2〜3文で示す",
        "- 思想史的背景や代表思想家の文脈を1〜2文で",
        "- 現代の知的関心や日常感覚との接続を1〜2文で",
        "- 平易だが知的な水準を保つ",
        "- 神山氏（経営者、現象学・認知科学・暗黙知に関心）が",
        "  読んで思考を刺激される文章にする",
    ]

    if related:
        lines += [
            "",
            "続けて、以下の関連概念それぞれについて、"
            f"『{concept['name_ja']}』との繋がりを 1〜2 文で書いてください。",
            "",
        ]
        for r in related:
            r_seed = " ".join((r.get("seed") or "").split())[:90]
            lines.append(
                f"- {r['name_ja']}（{r.get('name_en', '')}）"
                f"／領域：{r.get('domain', '')}／参考：{r_seed}"
            )
        lines += [
            "",
            "【出力形式】以下の形式を厳守してください。",
            ESSAY_MARKER,
            "（コラム本文 400〜600字）",
            RELATED_MARKER,
            *[f"{r['name_ja']}: （繋がりの説明 1〜2 文）" for r in related],
        ]
    return "\n".join(lines)


def _split_response(text: str, related: list[dict]) -> tuple[str, dict[str, str]]:
    """LLM 応答を (本文, {関連概念名: 説明}) に分割する。

    区切りが見つからない場合は全体を本文として返し、説明は空 dict。
    呼び出し側が seed fallback に倒す。
    """
    body = text
    notes: dict[str, str] = {}

    if RELATED_MARKER in text:
        head, _, tail = text.partition(RELATED_MARKER)
        body = head
        # "概念名: 説明" の行を拾う。名前は yaml 側の name_ja と突き合わせる。
        names = {r["name_ja"] for r in related}
        current = None
        for raw in tail.splitlines():
            line = raw.strip().lstrip("-・*").strip()
            if not line:
                continue
            m = re.match(r"^(.+?)\s*[:：]\s*(.*)$", line)
            if m and m.group(1).strip() in names:
                current = m.group(1).strip()
                notes[current] = m.group(2).strip()
            elif current:
                notes[current] = (notes[current] + " " + line).strip()

    body = body.replace(ESSAY_MARKER, "").strip()
    return body, notes


def _static_fallback(concept: dict) -> str:
    """Return the seed text as-is for the fallback essay."""
    seed = (concept.get("seed") or "").strip()
    if not seed:
        return f"{concept.get('name_ja', '本日の概念')}に関する解説の生成に失敗しました。"
    return seed


def _related_fallback(related: list[dict]) -> list[dict]:
    """LLM 解説が取れなかった関連概念を seed の 1 文目で埋める。

    「なぜ繋がるか」までは書けないが、概念名だけが並ぶより読める。
    ``is_fallback=True`` を立てて紙面側で区別できるようにする。
    """
    out = []
    for r in related:
        seed = " ".join((r.get("seed") or "").split())
        note = seed.split("。")[0] + "。" if "。" in seed else seed
        out.append({
            "id": r.get("id"),
            "name_ja": r.get("name_ja", ""),
            "name_en": r.get("name_en", ""),
            "domain": r.get("domain", ""),
            "note": note[:120],
            "is_fallback": True,
        })
    return out


def _merge_related(related: list[dict], notes: dict[str, str]) -> list[dict]:
    """関連概念に LLM の説明を貼る。取れなかったものは seed fallback。"""
    out = []
    for r in related:
        note = (notes.get(r.get("name_ja", "")) or "").strip()
        if note:
            out.append({
                "id": r.get("id"),
                "name_ja": r.get("name_ja", ""),
                "name_en": r.get("name_en", ""),
                "domain": r.get("domain", ""),
                "note": note,
                "is_fallback": False,
            })
        else:
            out.extend(_related_fallback([r]))
    return out


def write_essay(
    concept: dict,
    related: list[dict] | None = None,
    *,
    model: str = DEFAULT_MODEL,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    temperature: float = DEFAULT_TEMPERATURE,
) -> dict:
    """本文と関連概念の解説を **1 回の LLM 呼び出し**で生成する。

    Returns
    -------
    dict
        ``concept`` / ``essay`` / ``related`` / ``is_fallback`` / ``cost_usd``。
        ``related`` は ``{id, name_ja, name_en, domain, note, is_fallback}`` の
        リスト（``related`` 引数が空なら空リスト）。
    """
    related = related or []
    user_msg = _build_user_message(concept, related)

    try:
        response = llm.call_claude_with_retry(
            system=SYSTEM_PROMPT,
            user=user_msg,
            model=model,
            max_tokens=max_tokens,
            cache_system=True,
            tag="page4.concept",
        )
        raw = (response.text or "").strip()
        cost = response.cost_usd
        if not raw:
            print(
                "[concept_writer] WARN: empty LLM response, using static fallback",
                file=sys.stderr,
            )
            return {
                "concept": concept,
                "essay": _static_fallback(concept),
                "related": _related_fallback(related),
                "is_fallback": True,
                "cost_usd": cost,
            }

        essay, notes = _split_response(raw, related)
        if related and not notes:
            print(
                "[concept_writer] WARN: 関連概念の区切りをパースできませんでした "
                "（応答全体を本文として扱い、関連概念は seed fallback）",
                file=sys.stderr,
            )
        if not essay:
            essay = _static_fallback(concept)

        return {
            "concept": concept,
            "essay": essay,
            "related": _merge_related(related, notes),
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
            "related": _related_fallback(related),
            "is_fallback": True,
            "cost_usd": 0.0,
        }
