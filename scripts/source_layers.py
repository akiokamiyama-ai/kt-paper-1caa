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
# 層 3: Sonnet 必須（Tribune 知的核心、17 件、C133 で採用実績主導の精査）
# ---------------------------------------------------------------------------
# 内訳: 地政学 3 / 学術人文 6 / 経営思想 2 / 思想・科学哲学 + 文学 6
#
# 神山さん事業ドメイン直結度、美意識評価の決定性、過去採用実績を総合判断。
# 詳細は /tmp/phase_b_step3_layer3_detail.md 参照。
#
# C133 (Sprint 12, 2026-07-09) 降格 + dead weight 整理:
#   Phase B コスト目標 $30-50/月 に対する現状 $96/月 の圧縮。C132 の実測
#   30 日採用実績集計に基づき、以下 22 件を LAYER_3_SOURCES から除外。
#
#   Step 1 降格 11 件（採用ゼロ × Sonnet コスト大、合計約 $21/月 削減見込み）:
#   - Foresight（新潮社）（2026-05-18 に新潮QUE 統合で新規配信停止、後継は QUE）
#   - Stanford Encyclopedia of Philosophy（SEP）
#   - 集英社新書プラス
#   - Foreign Affairs（CFR）
#   - Philosophy Now
#   - Quanta Magazine
#   - 春秋社
#   - CSIS（戦略国際問題研究所）
#   - London Review of Books（LRB）
#   - 青土社（現代思想）
#   - DIAMONDハーバード・ビジネス・レビュー（DHBR）
#   ※ 降格後も layer 2（Haiku prefilter 経路）で評価継続。完全遮断ではない
#
#   Step 2 dead weight 11 件（30 日 eval ゼロ、コスト影響ゼロ、定義の健全化）:
#   - NBR（National Bureau of Asian Research）
#   - 日本認知科学会 / PhilPapers / WEBちくま（status=FAILED / BLOCKED）
#   - RAND Corporation / Harvard Business Review（HBR.org） / Brookings Institution
#   - Aeon（Psychology / Philosophy）（companies:Human Energy 経路の name collision、
#     実 URL は aeon.co で "Aeon" に吸収される dead entry）
#   - NBER Working Papers / Behavioral Scientist / 東京大学 公共政策大学院（GraSPP）
#   ※ fetch 復旧（BLOCKED/FAILED 解消）は別案件、observations.md に記録
#
# C132 (Sprint 12, 2026-07-09) 昇格（C133 でも維持）:
# - "Psyche"（Aeon 姉妹サイト、C116 追加、academic:国際）
# - "Literary Hub（LitHub）"（C125 追加、books:海外純文学）
# 両者は昇格直後で採用実績はまだ蓄積中。W9「内受容感覚」（7/19-25）期間の
# Psyche 採用実績を見て次回判断。
#
# BE-PAL（C123 追加）は layer 3 昇格せず（outdoor は CleverHiker layer 2 が
# 採用実績あり、Sprint 13 で再判断）。
LAYER_3_SOURCES: frozenset[str] = frozenset({
    # 地政学（3 件、C133 で 10 → 3）
    # "Shincho QUE（新潮QUE）" の geopolitics 経路は LAYER_3_DYNAMIC で扱う
    "Project Syndicate",
    "Foreign Policy",
    "War on the Rocks",
    # 学術人文（6 件、C133 で 15 → 6、Psyche 維持）
    "Aeon",
    "Psyche",  # C132 昇格（Aeon 姉妹、C116 追加、W9 内受容感覚期間の評価向上狙い）
    "3 Quarks Daily",
    "Public Books",
    "The Point Magazine",
    "n+1",
    # 経営思想（2 件、C133 で 5 → 2）
    "MIT Sloan Management Review",
    "McKinsey Insights",  # C84 昇格（採用 50 件/46 日、経営思想中核）
    # 思想・科学哲学 + 文学（6 件、C133 で 7 → 6、LitHub 維持）
    "New York Review of Books（NYRB）",
    "The Paris Review",
    "Literary Hub（LitHub）",  # C132 昇格（Paris Review 姉妹的、C125 追加、books:海外純文学）
    "The Marginalian（旧 Brain Pickings）",
    "AXIS",
    "Nautilus",  # C84 昇格（採用 8 件/46 日、§4.5.4 嗜好の本質と合致）
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
