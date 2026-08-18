"""領域キーワードの語境界判定 (C171, 2026-08-18).

背景
----
``_has_keyword`` は素の部分一致（``kw.lower() in text.lower()``）だったため、
短い英字略語が**別の単語の途中**にヒットしていた。C170 調査で archive 113 日
（表示記事 630 件）を走査した実測:

  DMA       → Goldman(10) landmark(7) roadmap(2) Friedman Freedman Feldman
              Steadman Madman                       … R3 誤検知 22 件
  EUV       → maneuver / Fleuve                     … R3 誤検知  2 件
  DSA       → EDSA（マニラの幹線道路）              … R3 誤検知  2 件
  AI Act    → "AI Actually"                         … R3 誤検知  1 件
  evolution → revolution / Revolutionary            … R6 誤検知  8 件
  Fed       → Confederacy / rebuffed                … R1 誤検知  2 件
  NBER      → Eisenberg                             … R6 誤検知  1 件

結果、3 面 R3「国際規制・テクノ覇権」枠に Goldman Sachs の決算記事や W 杯の
予想記事が載っていた（R3 充填 86 件のうち 24 件 = 28% が誤分類）。

対処は**先頭のみ語境界**。末尾を開けるのは複数形・派生語を通すため。末尾にも
境界を課す案は実測で ``evolutionary`` / ``sovereignty`` / ``export controls``
を巻き添えにしたので採らない。

Tests:
  a) 実測された誤検知が消える
  b) 真のキーワードは引き続きマッチする
  c) 複数形・派生語は通る（末尾を締めない理由）
  d) 和文キーワードは従来どおり部分一致
  e) TRAILING_BOUNDARY_KEYWORDS の例外
  f) 過去データ回帰: R3 から誤検知が全部消え、真の該当が残る
  g) キャッシュ・実装の健全性

Run::

    python3 -m tests.test_page3_keyword_boundary
"""

from __future__ import annotations

import sys

from scripts.selector.page3 import (
    R1_KEYWORDS,
    R3_KEYWORDS,
    R5_KEYWORDS,
    R6_KEYWORDS,
    TRAILING_BOUNDARY_KEYWORDS,
    _compile_keywords,
    _has_keyword,
    _region_for,
)

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
# (a) 実測された誤検知が消える
# ---------------------------------------------------------------------------

_OBSERVED_FALSE_POSITIVES = [
    # (text, keywords, 何にヒットしていたか)
    ("Goldman Sachs profit tops estimates on trading boom", R3_KEYWORDS, "DMA → Goldman"),
    ("BYD's landmark sales fuel debate", R3_KEYWORDS, "DMA → landmark"),
    ("Many international landmarks have been designed", R3_KEYWORDS, "DMA → landmarks"),
    ("The roadmap for 2027", R3_KEYWORDS, "DMA → roadmap"),
    ("In 2016, Ben Friedman wrote", R3_KEYWORDS, "DMA → Friedman"),
    ("CEO Bess Freedman discusses", R3_KEYWORDS, "DMA → Freedman"),
    ("The Madman Strikes Back", R3_KEYWORDS, "DMA → Madman"),
    ("a bold maneuver.", R3_KEYWORDS, "EUV → maneuver"),
    ("protests along EDSA in Manila", R3_KEYWORDS, "DSA → EDSA"),
    ("Governments Can't Agree on What AI Actually Is", R3_KEYWORDS, "AI Act → AI Actually"),
    ("A Sea Control Revolution?", R6_KEYWORDS, "evolution → Revolution"),
    ("The Revolutionary period", R6_KEYWORDS, "evolution → Revolutionary"),
    ("A Confederacy of Dunces", R1_KEYWORDS, "Fed → Confederacy"),
    ("the offer was rebuffed", R1_KEYWORDS, "Fed → rebuffed"),
    ("Professor Eisenberg argues", R6_KEYWORDS, "NBER → Eisenberg"),
]


def test_observed_false_positives_gone():
    for text, kws, label in _OBSERVED_FALSE_POSITIVES:
        _check(f"a: {label}", not _has_keyword(text, kws), text[:44])


# ---------------------------------------------------------------------------
# (b) 真のキーワードは引き続きマッチする
# ---------------------------------------------------------------------------

_TRUE_POSITIVES = [
    ("EU DMA enforcement begins against gatekeepers", R3_KEYWORDS, "DMA 本物"),
    ("The EU AI Act takes effect this month", R3_KEYWORDS, "AI Act 本物"),
    ("TSMC expands its foundry capacity", R3_KEYWORDS, "TSMC / foundry"),
    ("ASML ships a new EUV machine", R3_KEYWORDS, "ASML / EUV 本物"),
    ("Washington tightens export control rules", R3_KEYWORDS, "export control"),
    ("Huawei responds to the 5G ban", R3_KEYWORDS, "Huawei / 5G ban"),
    ("An antitrust probe into the platform", R3_KEYWORDS, "antitrust"),
    ("The Fed cut rates by 25bp", R1_KEYWORDS, "Fed 本物"),
    ("Sovereign debt restructuring talks", R1_KEYWORDS, "sovereign 本物"),
    ("New research in evolution and genetics", R6_KEYWORDS, "evolution 本物"),
    ("An NBER working paper on inequality", R6_KEYWORDS, "NBER / working paper"),
    ("A personal essay on grief", R5_KEYWORDS, "essay 本物"),
]


def test_true_positives_preserved():
    for text, kws, label in _TRUE_POSITIVES:
        _check(f"b: {label}", _has_keyword(text, kws), text[:44])


# ---------------------------------------------------------------------------
# (c) 複数形・派生語は通る（末尾を締めない理由）
# ---------------------------------------------------------------------------

_INFLECTIONS = [
    ("semiconductors shipments rose", R3_KEYWORDS, "semiconductor → semiconductors"),
    ("new export controls on chips", R3_KEYWORDS, "export control → export controls"),
    ("techno-authoritarianism spreads", R3_KEYWORDS, "techno-authoritarian → -ism"),
    ("evolutionary biology advances", R6_KEYWORDS, "evolution → evolutionary"),
    ("sovereignty disputes in the Arctic", R1_KEYWORDS, "sovereign → sovereignty"),
    ("several working papers were cited", R6_KEYWORDS, "working paper → papers"),
    ("a collection of essays", R5_KEYWORDS, "essay → essays"),
]


def test_inflections_still_match():
    for text, kws, label in _INFLECTIONS:
        _check(f"c: {label}", _has_keyword(text, kws), text[:44])


# ---------------------------------------------------------------------------
# (d) 和文キーワードは従来どおり部分一致
# ---------------------------------------------------------------------------

def test_japanese_substring_unchanged():
    cases = [
        ("半導体の輸出規制が強化される", R3_KEYWORDS, "半導体"),
        ("次世代半導体材料の開発", R3_KEYWORDS, "複合語の一部でもマッチ"),
        ("独禁法違反の疑い", R3_KEYWORDS, "独禁法"),
        ("個人情報保護委員会が勧告", R3_KEYWORDS, "個人情報保護"),
        ("量子コンピュータの進化", R6_KEYWORDS, "量子"),
    ]
    for text, kws, label in cases:
        _check(f"d: {label}", _has_keyword(text, kws), text[:30])


# ---------------------------------------------------------------------------
# (e) TRAILING_BOUNDARY_KEYWORDS
# ---------------------------------------------------------------------------

def test_trailing_boundary_set():
    _check("e1 AI Act が末尾境界の例外に入っている",
           "AI Act" in TRAILING_BOUNDARY_KEYWORDS)
    _check("e2 例外は最小限（実測で誤検知が出たものだけ）",
           len(TRAILING_BOUNDARY_KEYWORDS) <= 3,
           str(sorted(TRAILING_BOUNDARY_KEYWORDS)))
    # 例外に入れると複数形が落ちるので、入れてはいけないものの回帰
    _check("e3 export control は例外に入れない（export controls が落ちる）",
           "export control" not in TRAILING_BOUNDARY_KEYWORDS)


# ---------------------------------------------------------------------------
# (f) 過去データ回帰
# ---------------------------------------------------------------------------

def test_real_articles_reclassified():
    """C170 で誤分類が確認された実記事が R3 から外れること。"""
    cases = [
        ({"title": "Goldman Sachs profit tops estimates on trading boom",
          "description": "Quarterly results beat forecasts.",
          "source_name": "Reuters Business", "category": "business"},
         "Goldman 決算（2026-07-15 に R3 で掲載）"),
        ({"title": "Spain favorites to win 2026 World Cup, Goldman model shows",
          "description": "A statistical model.",
          "source_name": "Reuters World", "category": "geopolitics"},
         "W 杯予想（2026-05-31 に R3 で掲載）"),
        ({"title": "The Surprising Joys of a Crowded Hiking Trail",
          "description": "Many international landmarks have been designed to draw crowds.",
          "source_name": "Bloomberg Opinion", "category": "business"},
         "ハイキング（2026-05-24 に R3 で掲載）"),
    ]
    for art, label in cases:
        got = _region_for(art)
        _check(f"f1 {label} が R3 でなくなる", got != "R3", f"→ {got}")


def test_real_r3_articles_kept():
    """真に R3 な実記事は R3 のまま。"""
    cases = [
        ({"title": "EU AI Act: First Enforcement Cases Target Hiring Tools",
          "description": "Regulators opened enforcement actions under the AI Act.",
          "source_name": "Foreign Policy", "category": "geopolitics"}, "EU AI Act"),
        ({"title": "「ニンテンドースイッチ2」1万円値上げへ 半導体価格の上昇で",
          "description": "半導体価格の上昇が背景。",
          "source_name": "NHK ニュース 経済", "category": "business"}, "半導体値上げ"),
    ]
    for art, label in cases:
        got = _region_for(art)
        _check(f"f2 {label} は R3 のまま", got == "R3", f"→ {got}")


# ---------------------------------------------------------------------------
# (g) 実装の健全性
# ---------------------------------------------------------------------------

def test_compile_splits_ascii_and_japanese():
    pattern, japanese = _compile_keywords(tuple(R3_KEYWORDS))
    _check("g1 英字は正規表現にまとまる", pattern is not None)
    _check("g2 和文はそのまま残る（語境界を課さない）",
           "半導体" in japanese and "独禁法" in japanese,
           f"{len(japanese)} 件")
    # AI規制 は ASCII を含むが和文混じりなので substring 側
    _check("g3 和文混じり（AI規制）は substring 判定に回る",
           any("規制" in k for k in japanese))


def test_cache_is_used():
    a = _compile_keywords(tuple(R3_KEYWORDS))
    b = _compile_keywords(tuple(R3_KEYWORDS))
    _check("g4 同じキーワード集合はキャッシュされる（領域判定は高頻度）",
           a[0] is b[0])


def test_empty_text():
    _check("g5 空文字は False", not _has_keyword("", R3_KEYWORDS))


def main() -> int:
    print("C171: 領域キーワードの語境界判定\n")
    print("(a) 実測された誤検知が消える:")
    test_observed_false_positives_gone()
    print()
    print("(b) 真のキーワードは引き続きマッチ:")
    test_true_positives_preserved()
    print()
    print("(c) 複数形・派生語は通る:")
    test_inflections_still_match()
    print()
    print("(d) 和文は従来どおり部分一致:")
    test_japanese_substring_unchanged()
    print()
    print("(e) 末尾境界の例外:")
    test_trailing_boundary_set()
    print()
    print("(f) 過去データ回帰:")
    test_real_articles_reclassified()
    test_real_r3_articles_kept()
    print()
    print("(g) 実装の健全性:")
    test_compile_splits_ascii_and_japanese()
    test_cache_is_used()
    test_empty_text()
    print()
    print(f"=== {PASS} passed, {FAIL} failed ===")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
