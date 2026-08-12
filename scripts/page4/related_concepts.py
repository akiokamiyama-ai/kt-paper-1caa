"""第4面「今日の概念」の関連概念セクション用の概念選出（C158, Sprint 13, 2026-08-12）。

C155 で学術ニュース 3 本を廃止した結果、第4面が概念コラム 1 本だけになり
分量的に寂しくなった。`data/concepts.yaml` が持つ **グラフ構造**（``related``
フィールド）を紙面に可視化することで、面の分量を自然に増やしつつ
「次に掘りたい概念」への導線を作る。

選出は 3 段のフォールバックで行う。``related`` は有向グラフだが、
概念間の「繋がり」自体は本質的に無向なので、**逆参照（このIDを related に
挙げている他概念）も同格の関連として扱う**。

    段 1: ``related``（outgoing edge）
    段 2: 逆参照（incoming edge）— 不足分を補う
    段 3: 同じ ``domain`` の概念 — さらに不足する場合

実測（2026-08-12、222 概念）:
    * ``related`` が 2 件未満の概念は 13 件（5.9%）。1 件のみで 0 件は無い
    * 段 2 まで使うと **222/222 = 100%** が 2 件以上、95.5% が 3 件以上
    * 段 3 まで使えば全概念で 2 件以上を確保できる
    * ``related`` の参照先 ID は全て実在（壊れた参照 0 件）

決定性について:
    同じ概念なら毎回同じ関連概念が出るよう、``rng`` を渡さない限り
    **ID の辞書順**で安定ソートしてから採用する。日替わりで関連概念が
    入れ替わると「昨日と繋がりが違う」という混乱を生むため。
"""

from __future__ import annotations

import sys
from collections import defaultdict

# 紙面に出す関連概念の目標件数（依頼: 2-3 件）
TARGET_RELATED = 3
MIN_RELATED = 2


def build_incoming_map(concepts: list[dict]) -> dict[str, set[str]]:
    """``related`` の逆引き（id → その id を related に挙げている concept_id 群）。"""
    incoming: dict[str, set[str]] = defaultdict(set)
    for c in concepts:
        cid = c.get("id")
        if not cid:
            continue
        for rid in c.get("related") or []:
            incoming[rid].add(cid)
    return incoming


def select_related(
    concept: dict,
    concepts: list[dict],
    *,
    limit: int = TARGET_RELATED,
) -> list[dict]:
    """``concept`` に対する関連概念を最大 ``limit`` 件返す。

    Returns
    -------
    list[dict]
        concept dict のリスト（``id`` / ``name_ja`` / ``name_en`` / ``domain`` /
        ``thinkers`` / ``seed`` を含む）。関連が 1 件も見つからなければ空リスト。
        各 dict には選出経路を示す ``_relation_source``
        （``"related"`` / ``"incoming"`` / ``"domain"``）を付与する。
    """
    by_id = {c["id"]: c for c in concepts if c.get("id")}
    cid = concept.get("id")
    picked: list[dict] = []
    seen: set[str] = {cid} if cid else set()

    def _take(ids, source: str) -> None:
        for rid in sorted(ids):
            if len(picked) >= limit:
                return
            if rid in seen or rid not in by_id:
                continue
            seen.add(rid)
            entry = dict(by_id[rid])
            entry["_relation_source"] = source
            picked.append(entry)

    # 段 1: related（outgoing）。yaml の記載順を尊重したいので sorted せず原順。
    for rid in concept.get("related") or []:
        if len(picked) >= limit:
            break
        if rid in seen or rid not in by_id:
            continue
        seen.add(rid)
        entry = dict(by_id[rid])
        entry["_relation_source"] = "related"
        picked.append(entry)

    # 段 2: 逆参照（incoming）
    if len(picked) < limit:
        incoming = build_incoming_map(concepts)
        _take(incoming.get(cid, set()), "incoming")

    # 段 3: 同 domain
    if len(picked) < limit:
        domain = concept.get("domain")
        same = {
            c["id"] for c in concepts
            if c.get("domain") == domain and c.get("id") != cid
        }
        _take(same, "domain")

    if len(picked) < MIN_RELATED:
        print(
            f"[related_concepts] WARN: {cid} の関連概念が {len(picked)} 件しか "
            f"見つかりません（目標 {MIN_RELATED} 件以上）。"
            "concepts.yaml の related / domain を確認してください。",
            file=sys.stderr,
        )
    return picked
