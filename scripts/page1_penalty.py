"""Page I source-based soft penalties.

C81 段階 2 (Sprint 9, 2026-06-13, Fable review M6 god module 分割): 旧
``regen_front_page_v2.py`` から Page I 限定 penalty 機構を切り出した。

設計（旧 regen_front_page_v2 docstring 転記）
============================================

神山さんが既に有料購読しており、いずれ必ず読む媒体は Tribune が再露出する
価値が低い。第1面選定で final_score 計算後に減点する形で頻出を抑制する。

適用範囲：第1面（``run_pipeline``）のみ。Page IV academic / Page V serendipity /
Page VI leisure は別の選定経路を通り、本 penalty の影響を受けない。

Foresight (-10.0)
------------------

Sprint 5 ポストモーメント (2026-05-04): -5 では Foresight が第1面 TOP に
出ることが 5/4 archive で実証された（"UAE OPEC 離脱" 38.30 で TOP）。
30 日観察を待たず -10 に強化、約 26% 削減効果（スケール 31-38 に対して）。

Shincho QUE (0.0、休止中)
--------------------------

C42 案A (2026-06-04): 旧 Foresight 後継として導入された新潮QUE。神山さんは
QUE 有料会員。

- 6/4 初期値 -5.0（Foresight -10 より弱め、初動観察用）
- 6/5 W2 Day 6 朝刊で QUE 採用 0 件 → 神山さん指示で 0.0 に外して様子見
- 将来：QUE が紙面占有過剰なら -3 / -5 / -10 に再強化、Foresight 在庫枯渇後の
  バランス次第
"""

from __future__ import annotations


# Foresight (新潮社 — 旧 ASCII 名で sources/geopolitics.md に登録)
FORESIGHT_PENALTY: float = -10.0
FORESIGHT_PATTERNS: tuple[str, ...] = ("Foresight",)

# Shincho QUE (Foresight 後継、現状ペナルティ休止中)
SHINCHO_QUE_PENALTY: float = 0.0
SHINCHO_QUE_PATTERNS: tuple[str, ...] = ("Shincho QUE", "新潮QUE")


def apply_page1_source_penalty(article: dict) -> float:
    """Return the Page-I-only soft penalty for an article based on source name.

    Returns 0.0 when no penalty applies. 神山さん購読中の媒体（Foresight /
    新潮QUE）に対して、Page I 過剰露出を抑制する soft penalty。順序：
    Foresight → Shincho QUE → no-op。Other paid-subscription sources (HBR /
    WSJ / FT / 日経 等) は据え置き。
    """
    source_name = article.get("source_name", "") or ""
    for pattern in FORESIGHT_PATTERNS:
        if pattern in source_name:
            return FORESIGHT_PENALTY
    for pattern in SHINCHO_QUE_PATTERNS:
        if pattern in source_name:
            return SHINCHO_QUE_PENALTY
    return 0.0
