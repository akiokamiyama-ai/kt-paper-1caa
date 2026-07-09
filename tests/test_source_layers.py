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


def test_layer3_count_39_static_plus_1_dynamic():
    """C132 神山さん判断後の層 3 = 40 件（39 静的 + 1 動的）.

    Shincho QUE（新潮QUE）は LAYER_1_SOURCES に登録しつつ、category=geopolitics
    のときだけ層 3 にする動的振り分け。これにより業務上の「層 3 = 40 件」と
    LAYER_3_SOURCES frozenset の件数 (39) が乖離するが、合算で 40。

    C132 (Sprint 12, 2026-07-09) で C84 の 37 → 39 に増加:
    - Psyche (Aeon 姉妹、C116 追加、W9 内受容感覚期間の評価向上狙い)
    - Literary Hub（LitHub） (Paris Review 姉妹、C125 追加、books:海外純文学)
    """
    _check(
        "a2 LAYER_3_SOURCES = 39 件（静的、QUE geopolitics 経路は dynamic 1 件で別管理）",
        len(sl.LAYER_3_SOURCES) == 39,
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
        sl.LAYER_COUNTS == {"layer_1": 14, "layer_3": 39, "layer_3_dynamic": 1},
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
    cases = [
        "Foresight（新潮社）",
        "Foreign Affairs（CFR）",
        "Project Syndicate",
        "War on the Rocks",
        "Foreign Policy",
    ]
    all_ok = all(sl.classify_layer(src) == 3 for src in cases)
    _check("b3 地政学コア → 層 3", all_ok)


def test_classify_layer_3_for_academic_cores():
    cases = [
        "集英社新書プラス",
        "Aeon",
        "Stanford Encyclopedia of Philosophy（SEP）",
        "Public Books",
        "n+1",
    ]
    all_ok = all(sl.classify_layer(src) == 3 for src in cases)
    _check("b4 学術人文コア → 層 3", all_ok)


def test_classify_layer_3_for_c84_promoted():
    """C84 で layer_2 から layer_3 に昇格した 2 件."""
    _check(
        "b5 C84 昇格: McKinsey Insights → 層 3",
        sl.classify_layer("McKinsey Insights") == 3,
    )
    _check(
        "b6 C84 昇格: Nautilus → 層 3",
        sl.classify_layer("Nautilus") == 3,
    )


def test_classify_layer_3_for_thought_science_philosophy():
    cases = [
        "New York Review of Books（NYRB）",
        "The Paris Review",
        "Quanta Magazine",
        "The Marginalian（旧 Brain Pickings）",
        "AXIS",
        "Nautilus",  # C84 昇格
    ]
    all_ok = all(sl.classify_layer(src) == 3 for src in cases)
    _check("b7 思想・科学哲学（6 件、C84 後）→ 層 3", all_ok)


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
    test_layer3_count_39_static_plus_1_dynamic()
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
