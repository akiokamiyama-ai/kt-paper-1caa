"""3-tier source classification for Stage 2 Haiku/Sonnet routing.

C85 段階 1 (Sprint 10, 2026-06-14, Phase B Step 4 sub-step 1):
Stage 2 を「Sonnet 一括」から「層 1=Haiku のみ / 層 2=Haiku pre-filter →
上位 Sonnet / 層 3=Sonnet 必須」の 3 層構造に再編する設計の単一 source of
truth。

設計の根拠と運用ルールは以下のドキュメント参照:

- `/tmp/phase_b_step3_design.md` (C83 設計、agent a912fa8f8cd367794)
- `/tmp/phase_b_step3_layer3_detail.md` (C83b 層 3 詳細、agent ad9ff940fb8c3921a)
- `/tmp/phase_b_step3_c84_update.md` (C84 神山さん判断反映、Nautilus + McKinsey 昇格)

API
----

- ``LAYER_1_SOURCES`` (frozenset[str], 14 件): 完全採用確実枠 + 速報通信社系。
- ``LAYER_3_SOURCES`` (frozenset[str], 38 件): Tribune 知的核心、Sonnet 必須。
- ``LAYER_3_DYNAMIC`` (dict[str, tuple[str, ...]]): 動的振り分け。Shincho QUE は
  category=geopolitics のみ層 3、business は層 1 経路。
- ``classify_layer(source_name, category=None) -> int``: 1 / 2 / 3 のいずれか。
- ``check_layer_consistency(registry=None) -> list[str]``: sources/*.md との整合
  不整合がある場合は警告メッセージのリスト、整合時は空リスト。

層 2 は明示しない（layer_1 / layer_3 のどちらでもないものが暗黙の層 2）。
sources/*.md に新規追加された source は自動的に層 2 として扱われる。
"""

from __future__ import annotations


# ---------------------------------------------------------------------------
# 層 1: Haiku のみ評価で十分（採用確実 or 速報通信社系、14 件）
# ---------------------------------------------------------------------------
# - HEADLINES_ALLOWED_SOURCES の 7 件（page2 Today's Headlines 確定枠）
# - 通信社・主要紙・公式発表 7 件（速報性質、Haiku で十分判定可能）
#
# Shincho QUE は category=business 経路のみ層 1 で評価される。LAYER_3_DYNAMIC
# と classify_layer() の協調で実装。
LAYER_1_SOURCES: frozenset[str] = frozenset({
    # HEADLINES_ALLOWED_SOURCES 由来（7 件）
    "NHK ニュース 主要",
    "NHK ニュース 経済",
    "Yahoo! ニュース 経済",
    "BBC Business",
    "The Economist",          # 注: 論考枠は C75 続編で sub-feed 分離後に層 3 化検討
    "Financial Times（FT）",  # 注: 同上
    "Shincho QUE（新潮QUE）",  # business category のみ層 1（LAYER_3_DYNAMIC 参照）
    # 通信社・速報・公式発表（7 件）
    "Reuters Business",
    "Reuters World",
    "日本経済新聞（電子版）",
    "朝日新聞デジタル 経済",
    "経済産業省ニュースリリース",
    "個人情報保護委員会",
    "公正取引委員会 報道発表",
})


# ---------------------------------------------------------------------------
# 層 3: Sonnet 必須（Tribune 知的核心、38 件、C84 で Nautilus + McKinsey 昇格）
# ---------------------------------------------------------------------------
# 内訳: 地政学 11 / 学術人文 14 / 経営思想 5 / 思想・科学哲学 6 / 行動経済 2
#
# 神山さん事業ドメイン直結度、美意識評価の決定性、過去採用実績を総合判断。
# 詳細は /tmp/phase_b_step3_layer3_detail.md 参照。
LAYER_3_SOURCES: frozenset[str] = frozenset({
    # 地政学（11 件）
    "Foresight（新潮社）",
    # "Shincho QUE（新潮QUE）" の geopolitics 経路は LAYER_3_DYNAMIC で扱う
    "Foreign Affairs（CFR）",
    "Project Syndicate",
    "Foreign Policy",
    "Brookings Institution",
    "CSIS（戦略国際問題研究所）",
    "War on the Rocks",
    "RAND Corporation",
    "NBR（National Bureau of Asian Research）",
    "東京大学 公共政策大学院（GraSPP）",
    # 学術人文（14 件）
    "集英社新書プラス",
    "春秋社",
    "青土社（現代思想）",
    "WEBちくま",
    "日本認知科学会",
    "Aeon",
    "Philosophy Now",
    "Stanford Encyclopedia of Philosophy（SEP）",
    "PhilPapers",
    "3 Quarks Daily",
    "Public Books",
    "The Point Magazine",
    "n+1",
    "London Review of Books（LRB）",
    # 経営思想（5 件、C84 で McKinsey 昇格）
    "MIT Sloan Management Review",
    "Harvard Business Review（HBR.org）",
    "Aeon（Psychology / Philosophy）",
    "DIAMONDハーバード・ビジネス・レビュー（DHBR）",
    "McKinsey Insights",  # C84 昇格（採用 50 件/46 日、経営思想中核）
    # 思想・科学哲学（6 件、C84 で Nautilus 昇格）
    "New York Review of Books（NYRB）",
    "The Paris Review",
    "Quanta Magazine",
    "The Marginalian（旧 Brain Pickings）",
    "AXIS",
    "Nautilus",  # C84 昇格（採用 8 件/46 日、§4.5.4 嗜好の本質と合致）
    # 行動経済（2 件、採用 0 件だが層 3 維持、score 分布ログで真因調査）
    "Behavioral Scientist",
    "NBER Working Papers",
})


# ---------------------------------------------------------------------------
# 動的振り分け（category 依存）
# ---------------------------------------------------------------------------
# Shincho QUE は記事ごとに `Article.raw["tribune_category"]` (C76/C79) で
# business / books / geopolitics のいずれかが決まる。これに応じて層を変える。
#
# キー: source_name (LAYER_1_SOURCES に含まれる前提)
# 値: 「この category なら層 3 にする」category タプル
#
# 例: Shincho QUE は LAYER_1_SOURCES にあるが、category=geopolitics なら層 3
# に格上げ（Foresight 後継として論考性質、Sonnet 評価）。
LAYER_3_DYNAMIC: dict[str, tuple[str, ...]] = {
    "Shincho QUE（新潮QUE）": ("geopolitics",),
}


# ---------------------------------------------------------------------------
# 公開 API
# ---------------------------------------------------------------------------

def classify_layer(source_name: str | None, category: str | None = None) -> int:
    """Classify article source into 1 / 2 / 3 layer.

    Parameters
    ----------
    source_name :
        ``article.get("source_name")``。空 / None は層 2（暗黙のデフォルト）。
    category :
        ``article.get("category")``。LAYER_3_DYNAMIC の判定で使う。None の場合
        は動的振り分けをスキップ（source_name のみで判定）。

    Returns
    -------
    int
        1 = layer 1 (Haiku のみ)、2 = layer 2 (Haiku pre-filter → Sonnet 上位)、
        3 = layer 3 (Sonnet 必須)。

    Priority
    --------
    判定順は以下。LAYER_3_DYNAMIC は LAYER_1/3 の判定より前に走る：

    1. LAYER_3_DYNAMIC: source が動的判定対象 + category 一致 → 層 3
       (例: QUE geopolitics → 層 3)
    2. LAYER_3_SOURCES: 静的層 3 リストに含まれる → 層 3
    3. LAYER_1_SOURCES: 静的層 1 リストに含まれる → 層 1
       (例: QUE が LAYER_3_DYNAMIC をすり抜けた場合の business 経路)
    4. デフォルト: 層 2

    Tribune category subcategory（例: ``books:自然科学ノンフィクション``）の
    場合は ``startswith`` 緩和を適用しない。category は厳密一致で判定する。
    """
    if not source_name:
        return 2
    # 1) 動的振り分けが先（QUE の geopolitics 経路を逃さない）
    dynamic_categories = LAYER_3_DYNAMIC.get(source_name)
    if dynamic_categories and category:
        if category in dynamic_categories:
            return 3
    # 2) 静的層 3
    if source_name in LAYER_3_SOURCES:
        return 3
    # 3) 静的層 1
    if source_name in LAYER_1_SOURCES:
        return 1
    # 4) 残り全部 層 2
    return 2


def check_layer_consistency(
    sources_dir: object | None = None,
) -> list[str]:
    """Detect inconsistencies between layer config and sources/*.md.

    検証項目:

    - LAYER_1_SOURCES の全件が SourceRegistry に存在する
    - LAYER_3_SOURCES の全件が SourceRegistry に存在する
    - LAYER_3_DYNAMIC の key が LAYER_1_SOURCES に存在する
    - LAYER_1 と LAYER_3 が重複しない（LAYER_3_DYNAMIC の key 以外）

    Parameters
    ----------
    sources_dir : Path | None
        ``sources/`` ディレクトリ。None の場合はデフォルト（プロジェクト直下）。

    Returns
    -------
    list[str]
        不整合メッセージのリスト。整合時は空リスト。CI で
        ``assert not check_layer_consistency()`` でゲートする想定。
    """
    from pathlib import Path
    from .selector.source_registry import build_registry

    if sources_dir is None:
        sources_dir = Path(__file__).resolve().parent.parent / "sources"
    reg = build_registry(sources_dir)

    issues: list[str] = []

    # 1) layer 1 が registry に全件存在
    for name in LAYER_1_SOURCES:
        if name not in reg.sources_by_name:
            issues.append(
                f"LAYER_1_SOURCES の {name!r} が SourceRegistry に存在しない "
                f"(sources/*.md に登録なし、layer 設定の typo 可能性)"
            )

    # 2) layer 3 が registry に全件存在
    for name in LAYER_3_SOURCES:
        if name not in reg.sources_by_name:
            issues.append(
                f"LAYER_3_SOURCES の {name!r} が SourceRegistry に存在しない"
            )

    # 3) LAYER_3_DYNAMIC の key は LAYER_1_SOURCES に存在する想定
    #    (動的振り分けは「層 1 デフォルト → 一部 category で層 3」のパターン)
    for name in LAYER_3_DYNAMIC:
        if name not in LAYER_1_SOURCES:
            issues.append(
                f"LAYER_3_DYNAMIC の {name!r} が LAYER_1_SOURCES に無い "
                f"(動的振り分けは layer 1 をベースに category 条件で層 3 化する設計)"
            )
        if name not in reg.sources_by_name:
            issues.append(
                f"LAYER_3_DYNAMIC の {name!r} が SourceRegistry に存在しない"
            )

    # 4) LAYER_1 と LAYER_3 の重複（LAYER_3_DYNAMIC の key は除外）
    overlap = (LAYER_1_SOURCES & LAYER_3_SOURCES) - set(LAYER_3_DYNAMIC)
    if overlap:
        issues.append(
            f"LAYER_1_SOURCES と LAYER_3_SOURCES が重複: {sorted(overlap)!r} "
            f"(LAYER_3_DYNAMIC で動的振り分けする想定なら key を追加する)"
        )

    return issues


# 公開 API メタ情報（CI / dashboard 用）
LAYER_COUNTS: dict[str, int] = {
    "layer_1": len(LAYER_1_SOURCES),
    "layer_3": len(LAYER_3_SOURCES),
    "layer_3_dynamic": len(LAYER_3_DYNAMIC),
}
