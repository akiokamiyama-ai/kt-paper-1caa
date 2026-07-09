"""Unit tests for scripts/source_layers.py (C85 Sub-Step 1).

Phase B Step 4 sub-step 1。3 層分類の単一 source of truth が想定通り動作
することを検証する。

Run::

    python3 -m tests.test_source_layers
"""

from __future__ import annotations

import sys
from pathlib import Path

from scripts import source_layers as sl

PASS = 0
FAIL = 0


def _check(label: str, condition: bool, detail: str = "") -> bool:
    global PASS, FAIL
    sym = "✓" if condition else "✗"
    line = f"  {sym} {label}"
    if detail:
        line += f"  ({detail})"
    print(line)
    if condition:
        PASS += 1
    else:
        FAIL += 1
    return condition


# ---------------------------------------------------------------------------
# (a) 件数 / 構造
# ---------------------------------------------------------------------------

def test_layer1_count_14():
    _check(
        "a1 LAYER_1_SOURCES = 14 件（HEADLINES 7 + 通信社・公式発表 7）",
        len(sl.LAYER_1_SOURCES) == 14,
        f"got {len(sl.LAYER_1_SOURCES)}",
    )


def test_layer3_count_17_static_plus_1_dynamic():
    """C133 神山さん判断後の層 3 = 18 件（17 静的 + 1 動的）.

    Shincho QUE（新潮QUE）は LAYER_1_SOURCES に登録しつつ、category=geopolitics
    のときだけ層 3 にする動的振り分け。これにより業務上の「層 3 = 18 件」と
    LAYER_3_SOURCES frozenset の件数 (17) が乖離するが、合算で 18。

    C133 (Sprint 12, 2026-07-09) 降格 + dead weight 整理で 39 → 17:
    - Step 1: 採用ゼロ × 高コスト 11 件降格（Foresight / SEP / 集英社新書
      プラス / Foreign Affairs / Philosophy Now / Quanta / 春秋社 / CSIS /
      LRB / 青土社 / DHBR）→ Phase B $21/月 削減見込み
    - Step 2: eval ゼロ dead weight 11 件を LAYER_3 定義から除外（NBR /
      日本認知科学会 / PhilPapers / RAND / HBR.org / Brookings / Aeon P&P /
      NBER / WEBちくま / Behavioral Scientist / GraSPP）
    - 維持: 採用実績 15 件（Aeon / Project Syndicate / Foreign Policy /
      War on the Rocks / 3 Quarks Daily / Public Books / The Point Magazine /
      n+1 / MIT SMR / McKinsey / NYRB / Paris Review / Marginalian / AXIS /
      Nautilus）+ C132 新規 2 件（Psyche / LitHub）= 17 件
    """
    _check(
        "a2 LAYER_3_SOURCES = 17 件（静的、QUE geopolitics 経路は dynamic 1 件で別管理）",
        len(sl.LAYER_3_SOURCES) == 17,
        f"got {len(sl.LAYER_3_SOURCES)}",
    )
    _check(
        "a3 LAYER_3_DYNAMIC = 1 件（QUE geopolitics 経路のみ）",
        len(sl.LAYER_3_DYNAMIC) == 1
        and "Shincho QUE（新潮QUE）" in sl.LAYER_3_DYNAMIC
        and sl.LAYER_3_DYNAMIC["Shincho QUE（新潮QUE）"] == ("geopolitics",),
    )


def test_layer_counts_meta():
    _check(
        "a4 LAYER_COUNTS メタ情報の整合",
        sl.LAYER_COUNTS == {"layer_1": 14, "layer_3": 17, "layer_3_dynamic": 1},
        f"got {sl.LAYER_COUNTS}",
    )


def test_no_overlap_between_layer1_and_layer3():
    """LAYER_1 と LAYER_3 が重複しないこと（LAYER_3_DYNAMIC key は例外）."""
    overlap = (sl.LAYER_1_SOURCES & sl.LAYER_3_SOURCES) - set(sl.LAYER_3_DYNAMIC)
    _check(
        "a5 LAYER_1 ∩ LAYER_3 = ∅（dynamic key を除く）",
        overlap == set(),
        f"unexpected overlap: {overlap}",
    )


# ---------------------------------------------------------------------------
# (b) classify_layer の挙動
# ---------------------------------------------------------------------------

def test_classify_layer_1_for_headlines_sources():
    cases = [
        "NHK ニュース 主要",
        "BBC Business",
        "The Economist",
        "Financial Times（FT）",
        "Yahoo! ニュース 経済",
    ]
    all_ok = all(sl.classify_layer(src) == 1 for src in cases)
    _check("b1 HEADLINES_ALLOWED_SOURCES → 層 1", all_ok)


def test_classify_layer_1_for_telcom_sources():
    cases = [
        "Reuters Business",
        "Reuters World",
        "日本経済新聞（電子版）",
        "朝日新聞デジタル 経済",
        "経済産業省ニュースリリース",
    ]
    all_ok = all(sl.classify_layer(src) == 1 for src in cases)
    _check("b2 通信社・主要紙・公式発表 → 層 1", all_ok)


def test_classify_layer_3_for_geopolitics_cores():
    """C133 降格後の地政学コア（3 件）→ 層 3.

    降格: Foresight / Foreign Affairs / Brookings / CSIS / RAND / NBR / GraSPP
    """
    cases = [
        "Project Syndicate",
        "War on the Rocks",
        "Foreign Policy",
    ]
    all_ok = all(sl.classify_layer(src) == 3 for src in cases)
    _check("b3 地政学コア → 層 3（C133 降格後 3 件）", all_ok)


def test_classify_layer_3_for_academic_cores():
    """C133 降格後の学術人文コア（6 件）→ 層 3、C132 昇格 Psyche 維持.

    降格: 集英社新書プラス / SEP / Philosophy Now / 春秋社 / LRB / 青土社 /
    WEBちくま / 日本認知科学会 / PhilPapers
    """
    cases = [
        "Aeon",
        "Psyche",  # C132 昇格、C133 で維持
        "Public Books",
        "The Point Magazine",
        "n+1",
        "3 Quarks Daily",
    ]
    all_ok = all(sl.classify_layer(src) == 3 for src in cases)
    _check("b4 学術人文コア → 層 3（C133 降格後 6 件）", all_ok)


def test_classify_layer_3_for_c84_promoted():
    """C84 で layer_2 から layer_3 に昇格した 2 件（C133 でも維持）."""
    _check(
        "b5 C84 昇格: McKinsey Insights → 層 3（C133 維持）",
        sl.classify_layer("McKinsey Insights") == 3,
    )
    _check(
        "b6 C84 昇格: Nautilus → 層 3（C133 維持）",
        sl.classify_layer("Nautilus") == 3,
    )


def test_classify_layer_3_for_thought_science_philosophy():
    """C133 降格後の思想・科学哲学 + 文学（6 件）→ 層 3.

    降格: Quanta Magazine / DHBR
    C132 で LitHub 昇格、C133 で維持
    """
    cases = [
        "New York Review of Books（NYRB）",
        "The Paris Review",
        "Literary Hub（LitHub）",  # C132 昇格、C133 で維持
        "The Marginalian（旧 Brain Pickings）",
        "AXIS",
        "Nautilus",  # C84 昇格
    ]
    all_ok = all(sl.classify_layer(src) == 3 for src in cases)
    _check("b7 思想・科学哲学 + 文学 → 層 3（C133 降格後 6 件）", all_ok)


def test_classify_layer_2_for_c133_demoted():
    """C133 で LAYER_3 → LAYER_2 に降格した 11 件 + dead weight 除外 11 件は
    暗黙のデフォルト（layer 2）で扱われる."""
    demoted = [
        # Step 1 降格 11 件（採用ゼロ × 高コスト）
        "Foresight（新潮社）",
        "Stanford Encyclopedia of Philosophy（SEP）",
        "集英社新書プラス",
        "Foreign Affairs（CFR）",
        "Philosophy Now",
        "Quanta Magazine",
        "春秋社",
        "CSIS（戦略国際問題研究所）",
        "London Review of Books（LRB）",
        "青土社（現代思想）",
        "DIAMONDハーバード・ビジネス・レビュー（DHBR）",
        # Step 2 dead weight 11 件（eval ゼロ、LAYER_3 定義除外）
        "NBR（National Bureau of Asian Research）",
        "日本認知科学会",
        "PhilPapers",
        "RAND Corporation",
        "Harvard Business Review（HBR.org）",
        "Brookings Institution",
        "Aeon（Psychology / Philosophy）",
        "NBER Working Papers",
        "WEBちくま",
        "Behavioral Scientist",
        "東京大学 公共政策大学院（GraSPP）",
    ]
    all_ok = all(sl.classify_layer(src) == 2 for src in demoted)
    _check(
        "b8 C133 降格 11 件 + dead weight 11 件 → 層 2（暗黙のデフォルト）",
        all_ok,
    )


# ---------------------------------------------------------------------------
# (c) Shincho QUE 動的振り分け
# ---------------------------------------------------------------------------

def test_que_dynamic_business_to_layer1():
    _check(
        "c1 QUE category=business → 層 1（Headlines pool）",
        sl.classify_layer("Shincho QUE（新潮QUE）", "business") == 1,
    )


def test_que_dynamic_geopolitics_to_layer3():
    _check(
        "c2 QUE category=geopolitics → 層 3（Foresight 後継、Sonnet 必須）",
        sl.classify_layer("Shincho QUE（新潮QUE）", "geopolitics") == 3,
    )


def test_que_dynamic_books_falls_through_to_layer1():
    """C76 動的マッピングで category=books になる QUE 記事は動的判定にヒット
    しないため、LAYER_1_SOURCES の静的所属で層 1 になる。
    """
    _check(
        "c3 QUE category=books（動的ヒットせず）→ 層 1",
        sl.classify_layer("Shincho QUE（新潮QUE）", "books") == 1,
    )


def test_que_dynamic_no_category_to_layer1():
    """category が渡されない場合（page1 旧経路など）は動的判定スキップ → 層 1."""
    _check(
        "c4 QUE category=None → 層 1（動的判定スキップ、静的所属 fallback）",
        sl.classify_layer("Shincho QUE（新潮QUE）", None) == 1,
    )


# ---------------------------------------------------------------------------
# (d) デフォルト / 境界
# ---------------------------------------------------------------------------

def test_unknown_source_defaults_to_layer2():
    _check(
        "d1 未知 source → 層 2（暗黙のデフォルト）",
        sl.classify_layer("Brand New Future Source") == 2,
    )


def test_empty_source_defaults_to_layer2():
    _check(
        "d2 空文字列 → 層 2",
        sl.classify_layer("") == 2,
    )


def test_none_source_defaults_to_layer2():
    _check(
        "d3 None → 層 2",
        sl.classify_layer(None) == 2,
    )


def test_known_layer2_source():
    """sources/*.md の他 source は層 2 暗黙デフォルト."""
    _check(
        "d4 東洋経済オンライン（layer 2 中堅論考）→ 層 2",
        sl.classify_layer("東洋経済オンライン") == 2,
    )
    _check(
        "d5 cooking 系（リュウジのバズレシピ）→ 層 2",
        sl.classify_layer("リュウジのバズレシピ") == 2,
    )


# ---------------------------------------------------------------------------
# (e) check_layer_consistency
# ---------------------------------------------------------------------------

def test_consistency_passes_with_default_sources():
    """現実の sources/*.md と層分類の整合性: 不整合 0 件."""
    issues = sl.check_layer_consistency()
    _check(
        "e1 sources/*.md と層分類: 不整合 0 件",
        issues == [],
        f"issues: {issues}" if issues else "all clear",
    )


def test_consistency_with_explicit_sources_dir():
    sources_dir = Path(__file__).resolve().parent.parent / "sources"
    issues = sl.check_layer_consistency(sources_dir=sources_dir)
    _check(
        "e2 sources_dir 明示渡し: 不整合 0 件",
        issues == [],
        f"issues: {issues}" if issues else "all clear",
    )


def main() -> int:
    print("source_layers unit tests (C85 Sub-Step 1, Phase B Step 4)")
    print()
    print("(a) 件数 / 構造:")
    test_layer1_count_14()
    test_layer3_count_17_static_plus_1_dynamic()
    test_layer_counts_meta()
    test_no_overlap_between_layer1_and_layer3()

    print()
    print("(b) classify_layer 基本:")
    test_classify_layer_1_for_headlines_sources()
    test_classify_layer_1_for_telcom_sources()
    test_classify_layer_3_for_geopolitics_cores()
    test_classify_layer_3_for_academic_cores()
    test_classify_layer_3_for_c84_promoted()
    test_classify_layer_3_for_thought_science_philosophy()
    test_classify_layer_2_for_c133_demoted()

    print()
    print("(c) Shincho QUE 動的振り分け:")
    test_que_dynamic_business_to_layer1()
    test_que_dynamic_geopolitics_to_layer3()
    test_que_dynamic_books_falls_through_to_layer1()
    test_que_dynamic_no_category_to_layer1()

    print()
    print("(d) デフォルト / 境界:")
    test_unknown_source_defaults_to_layer2()
    test_empty_source_defaults_to_layer2()
    test_none_source_defaults_to_layer2()
    test_known_layer2_source()

    print()
    print("(e) check_layer_consistency:")
    test_consistency_passes_with_default_sources()
    test_consistency_with_explicit_sources_dir()

    print()
    print(f"=== {PASS} passed, {FAIL} failed ===")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
