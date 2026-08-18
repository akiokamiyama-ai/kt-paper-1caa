"""第3面 空枠の原因切り分け (C170, 2026-08-18).

背景
----
3 面 R3「国際規制・テクノ覇権」の placeholder が全期間 24/113 日 (21.2%) と
突出していた（他領域は 0.9〜2.7%）。しかし原因が追えなかった。理由は 2 つ:

  1. ``fallback_reason`` が空枠を全部 ``"no_candidates"`` にしていた
     （dedup 全除外なのか、他領域に先取りされたのか、そもそも 0 件なのか
     区別できない）
  2. 本番経路の ``=== Page III summary ===`` は ``fallback_reason`` すら
     出力していなかった（dry-run 用の ``=== Page III selections ===`` は
     出していたが、cron 実行では呼ばれない）

C156「fallback したこと自体を記録しないと破損が可視化されない」の適用漏れ。

なお閾値による脱落は原因になり得ない —— ``_select_top_for_region`` は
threshold を適用しない（docs/page3_design_v1.md §13 Q2）。原因は排他的に 3 つ。

Tests:
  a) 3 つの原因が区別される
  b) fallback_detail に件数が入る
  c) 記事がある領域は reason=None のまま（後方互換）
  d) JSON ログに fallback_detail が載る
  e) 本番経路 (=== Page III summary ===) が理由を出力する
  f) 回帰: R3 は唯一 category/source の無条件マッチを持たない

Run::

    python3 -m tests.test_page3_fallback_reason
"""

from __future__ import annotations

import inspect
import sys

from scripts.selector import page3 as P
from scripts.selector.page3 import (
    REGION_DETECTION_ORDER,
    RegionSelection,
    _diagnose_empty_region,
    select_page3_articles,
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


def _art(url: str, title: str, desc: str = "", source: str = "", cat: str = "",
         score: float = 10.0) -> dict:
    return {
        "url": url, "title": title, "description": desc,
        "source_name": source, "category": cat, "final_score": score,
    }


# R3 のみにマッチする記事（半導体は R6/R5 のキーワードに無い）
_R3_ART = _art("u-r3", "TSMC が最先端ファウンドリを増強", "半導体の輸出規制をめぐる動き",
               source="Reuters Business", cat="business")
# R6 が先取りする記事（academic カテゴリは R6 が無条件マッチ）だが R3 keyword も持つ
_R3_KW_BUT_ACADEMIC = _art("u-steal", "半導体物理学の新展開", "quantum な話",
                           source="Quanta Magazine", cat="academic")


# ---------------------------------------------------------------------------
# (a) 3 つの原因が区別される
# ---------------------------------------------------------------------------

def test_no_candidates():
    pool = [_art("u1", "料理と発酵の話", "", cat="cooking")]
    reason, detail = _diagnose_empty_region("R3", pool, pool)
    _check("a1 該当 0 件 → no_candidates", reason == "no_candidates", reason)
    _check("a1b detail に matcher hit 0 が入る", "hit 0" in detail, detail)


def test_all_deduped():
    pool = [_R3_ART]
    reason, detail = _diagnose_empty_region("R3", pool, [])
    _check("a2 dedup で全除外 → all_deduped", reason == "all_deduped", reason)


def test_claimed_by_other_region():
    pool = [_R3_KW_BUT_ACADEMIC]
    # この記事は R3 keyword を持つが _region_for は R6 を返す
    owner = P._region_for(_R3_KW_BUT_ACADEMIC)
    reason, detail = _diagnose_empty_region("R3", pool, pool)
    _check("a3 他領域が先取り → claimed_by_other_region",
           owner == "R6" and reason == "claimed_by_other_region",
           f"owner={owner}, reason={reason}")
    _check("a3b detail に先取り先の領域が入る", "R6" in detail, detail)


def test_three_reasons_are_distinct():
    got = {
        _diagnose_empty_region("R3", [_art("x", "料理")], [_art("x", "料理")])[0],
        _diagnose_empty_region("R3", [_R3_ART], [])[0],
        _diagnose_empty_region("R3", [_R3_KW_BUT_ACADEMIC], [_R3_KW_BUT_ACADEMIC])[0],
    }
    _check("a4 3 原因が別々のコードになる", len(got) == 3, str(sorted(got)))


# ---------------------------------------------------------------------------
# (b) detail に件数が入る
# ---------------------------------------------------------------------------

def test_detail_has_counts():
    pool = [_R3_ART, _art("u2", "料理"), _art("u3", "音楽")]
    _, detail = _diagnose_empty_region("R3", pool, [])
    ok = "pool=3" in detail and "1 件" in detail
    _check("b1 detail に pool 件数と該当件数が入る", ok, detail)


def test_detail_survives_into_selection():
    sels, _, _ = select_page3_articles([_art("u1", "料理と発酵", cat="cooking")])
    r3 = sels["R3"]
    _check("b2 select_page3_articles が detail を埋める",
           r3.article is None and r3.fallback_detail is not None,
           str(r3.fallback_detail))


# ---------------------------------------------------------------------------
# (c) 後方互換
# ---------------------------------------------------------------------------

def test_filled_region_has_no_reason():
    sels, _, _ = select_page3_articles([_R3_ART])
    r3 = sels["R3"]
    ok = (r3.article is not None
          and r3.fallback_reason is None
          and r3.fallback_detail is None)
    _check("c1 記事がある領域は reason/detail とも None", ok,
           f"reason={r3.fallback_reason}, detail={r3.fallback_detail}")


def test_no_candidates_code_preserved():
    """既存ログ・テストが読む "no_candidates" の綴りを変えていないこと。"""
    sels, _, _ = select_page3_articles([_art("u1", "料理", cat="cooking")])
    _check("c2 該当 0 件のコードは従来通り no_candidates",
           sels["R3"].fallback_reason == "no_candidates",
           sels["R3"].fallback_reason)


def test_dataclass_default():
    sel = RegionSelection(region="R3", article=None, final_score=None,
                          fallback_reason="x")
    _check("c3 fallback_detail は省略可（既存の構築箇所を壊さない）",
           sel.fallback_detail is None)


# ---------------------------------------------------------------------------
# (d) JSON ログ
# ---------------------------------------------------------------------------

def test_json_log_includes_detail():
    src = inspect.getsource(P.write_page3_log)
    _check("d1 write_page3_log が fallback_detail を書く",
           '"fallback_detail"' in src)


# ---------------------------------------------------------------------------
# (e) 本番経路が理由を出力する（C156 の教訓）
# ---------------------------------------------------------------------------

def test_production_summary_prints_reason():
    from scripts import regen_front_page_v2 as R
    src = inspect.getsource(R)
    i = src.find("=== Page III summary ===")
    _check("e0 Page III summary セクションが存在する", i > 0)
    seg = src[i:i + 1600]
    _check("e1 本番 summary が fallback_reason を出力する",
           "fallback_reason" in seg, "C156: 諦めたことを記録する")
    _check("e2 本番 summary が fallback_detail を出力する",
           "fallback_detail" in seg)


# ---------------------------------------------------------------------------
# (f) 回帰: R3 の構造的な脆さを記録する
# ---------------------------------------------------------------------------

def test_r3_is_keyword_only():
    """R3 は 5 領域で唯一 category/source の無条件マッチを持たない。

    R1 は ``cat == "geopolitics"``、R5 は ``cat.startswith("books")``、
    R6 は ``cat.startswith("academic")`` で必ず候補が供給されるが、R3 は
    キーワード一致のみ。これが placeholder 率 21.2% の構造的な原因。
    この非対称性を変える時はこのテストも一緒に更新すること。
    """
    src = inspect.getsource(P._matches_R3)
    ok = "_has_keyword" in src and "_category_of" not in src
    _check("f1 _matches_R3 はキーワード判定のみ（無条件マッチ無し）", ok, src.strip()[-60:])

    for other in ("_matches_R1", "_matches_R5", "_matches_R6"):
        s = inspect.getsource(getattr(P, other))
        _check(f"f2 {other} は category による無条件マッチを持つ（R3 との非対称）",
               "_category_of" in s)


def test_detection_order_after_c155():
    _check("f3 判定順序は R6→R5→R3→R4→R1（C155 で R2 廃止）",
           REGION_DETECTION_ORDER == ("R6", "R5", "R3", "R4", "R1"),
           str(REGION_DETECTION_ORDER))
    _check("f4 R3 は 3 番目に判定される（R6/R5 が先に取れる）",
           REGION_DETECTION_ORDER.index("R3") == 2)


def main() -> int:
    print("C170: 第3面 空枠の原因切り分け\n")
    print("(a) 3 つの原因が区別される:")
    test_no_candidates()
    test_all_deduped()
    test_claimed_by_other_region()
    test_three_reasons_are_distinct()
    print()
    print("(b) detail に件数が入る:")
    test_detail_has_counts()
    test_detail_survives_into_selection()
    print()
    print("(c) 後方互換:")
    test_filled_region_has_no_reason()
    test_no_candidates_code_preserved()
    test_dataclass_default()
    print()
    print("(d) JSON ログ:")
    test_json_log_includes_detail()
    print()
    print("(e) 本番経路が理由を出力する:")
    test_production_summary_prints_reason()
    print()
    print("(f) 回帰: R3 の構造的な脆さ:")
    test_r3_is_keyword_only()
    test_detection_order_after_c155()
    print()
    print(f"=== {PASS} passed, {FAIL} failed ===")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
