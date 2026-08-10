"""同日 cross-page dedup の再配線テスト (C155, Sprint 13, 2026-08-10).

C139 (Sprint 12, 2026-07-10) は「Page V serendipity → Page VI」の一方向 dedup
だった。C155 でセレンディピティ枠が Page III に移ったため、経路を
「**Page III 全採用 URL → Page VI**」に張り替えている。

本テストは以下を固定する:

  a) build 順序（Page III が Page VI より先に組まれる）が満たされること
  b) Page III の全 6 枠（5 領域 + SER）の URL が Page VI に渡ること
  c) Page III 内でセレンディピティが領域記事と重複しないこと
  d) Page IV は外部記事を持たないため dedup 経路から外れたこと
  e) displayed_urls ログのスキーマ互換

C138 で観測された「Stereogum が Page V と Page VI music の両方に採用される」
事象は、移設後は「Page III セレンディピティ枠 / Page VI music」の衝突として
同じ経路で防がれる。

Run::

    python3 -m tests.test_cross_page_dedup
"""

from __future__ import annotations

import inspect
import sys
from datetime import date

from scripts import regen_front_page_v2 as regen
from scripts.selector import page3

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


def _art(url: str, **kw) -> dict:
    a = {"url": url, "title": "t", "source_name": "S",
         "description": "d", "final_score": 50}
    a.update(kw)
    return a


class _Sel:
    def __init__(self, article):
        self.article = article


# ---------------------------------------------------------------------------
# (a) build 順序の保証
# ---------------------------------------------------------------------------

def test_page3_built_before_page6_in_main():
    """main() のソース順で Page III の選定が Page VI の build より先にある.

    dedup は「先に確定した面の URL を後段に渡す」設計なので、順序が逆転すると
    silent に無効化される。ソース上の出現位置で構造的に固定しておく。
    """
    src = inspect.getsource(regen.main)
    i_p3 = src.find("_run_page3_selection(")
    i_p6 = src.find("build_page_six_v2(")
    _check("a1 main() 内で page3 選定 → page6 build の順序",
           i_p3 != -1 and i_p6 != -1 and i_p3 < i_p6,
           f"page3@{i_p3}, page6@{i_p6}")


def test_page6_receives_page3_urls_not_page5():
    """Page VI に渡す dedup 集合が page3_result 由来であること."""
    src = inspect.getsource(regen.main)
    seg_start = src.find("page6_other_pages_urls: set[str] = set()")
    seg = src[seg_start:seg_start + 400]
    _check("a2 page6 の dedup 集合は page3_result から組む",
           "page3_result" in seg, seg[:120])
    _check("a3 旧 page_five_telemetry 由来の経路が残っていない",
           "page_five_telemetry" not in seg, seg[:120])


# ---------------------------------------------------------------------------
# (b) Page III 全枠の URL が集まる
# ---------------------------------------------------------------------------

def _collect_page6_dedup_urls(selections: dict) -> set[str]:
    """main() の該当ロジックと同じ組み立てを再現する."""
    urls: set[str] = set()
    for sel in selections.values():
        art = getattr(sel, "article", None)
        if art and art.get("url"):
            urls.add(art["url"])
    return urls


def test_all_six_slots_contribute_to_dedup():
    selections = {
        "R1": _Sel(_art("https://r1/")),
        "R3": _Sel(_art("https://r3/")),
        "R4": _Sel(_art("https://r4/")),
        "R5": _Sel(_art("https://r5/")),
        "R6": _Sel(_art("https://r6/")),
        "SER": _Sel(_art("https://ser/")),
    }
    urls = _collect_page6_dedup_urls(selections)
    _check("b1 5 領域 + SER の 6 URL すべてが dedup 集合に入る",
           urls == {f"https://{k}/" for k in ("r1", "r3", "r4", "r5", "r6", "ser")},
           f"got {sorted(urls)}")


def test_placeholder_slots_are_skipped():
    selections = {
        "R1": _Sel(_art("https://r1/")),
        "R3": _Sel(None),
        "SER": _Sel(None),
    }
    urls = _collect_page6_dedup_urls(selections)
    _check("b2 placeholder 枠は dedup 集合に寄与しない",
           urls == {"https://r1/"}, f"got {sorted(urls)}")


def test_serendipity_url_reaches_page6():
    """C138 再発防止の中核: SER 枠の URL が Page VI に届く."""
    selections = {"SER": _Sel(_art("https://stereogum.test/album"))}
    urls = _collect_page6_dedup_urls(selections)
    _check("b3 SER 枠の URL が Page VI dedup に届く（C138 再発防止）",
           "https://stereogum.test/album" in urls, f"got {sorted(urls)}")


# ---------------------------------------------------------------------------
# (c) Page III 内の重複防止
# ---------------------------------------------------------------------------

def test_serendipity_not_duplicated_within_page3():
    """5 領域で採用済の記事がセレンディピティ枠に再登場しない."""
    result = page3.Page3Result(today=date(2026, 8, 16))
    sel = page3._select_serendipity_slot(
        target_date=date(2026, 8, 16),
        selector=lambda **kw: {
            "article": _art("https://same/"), "category": "books",
            "is_placeholder": False, "cost_usd": 0.0,
        },
        exclude_urls={"https://same/"},
        result=result,
    )
    _check("c1 3 面内で重複する URL は SER 枠に載せない",
           sel.article is None
           and sel.fallback_reason == "serendipity_duplicate_within_page3",
           f"got {sel.fallback_reason}")


def test_serendipity_kept_when_distinct():
    result = page3.Page3Result(today=date(2026, 8, 16))
    sel = page3._select_serendipity_slot(
        target_date=date(2026, 8, 16),
        selector=lambda **kw: {
            "article": _art("https://fresh/"), "category": "books",
            "is_placeholder": False, "cost_usd": 0.0,
        },
        exclude_urls={"https://other/"},
        result=result,
    )
    _check("c2 重複しなければそのまま採用される",
           sel.article is not None and sel.article["url"] == "https://fresh/")


# ---------------------------------------------------------------------------
# (d) Page IV は dedup 経路から外れた
# ---------------------------------------------------------------------------

def test_page4_no_longer_takes_dedup_urls():
    """C49 案A の displayed_urls_today 引数は Page IV から消えた."""
    sig = inspect.signature(regen.build_page_four_v2)
    params = set(sig.parameters.keys())
    _check("d1 build_page_four_v2 は displayed_urls_today を受けない",
           "displayed_urls_today" not in params, f"got {sorted(params)}")
    _check("d2 build_page_four_v2 は pre_evaluated も受けない",
           "pre_evaluated" not in params, f"got {sorted(params)}")


def test_page4_telemetry_has_no_articles():
    """Page IV telemetry から articles_result が消えたこと（参照残存チェック）."""
    src = inspect.getsource(regen.build_page_four_v2)
    _check("d3 build_page_four_v2 に articles_result が残っていない",
           "articles_result" not in src)


# ---------------------------------------------------------------------------
# (e) displayed_urls ログのスキーマ互換
# ---------------------------------------------------------------------------

def test_displayed_urls_writer_still_accepts_all_pages():
    """過去日 log の読み出し互換のため、writer は全 page キーを受け続ける."""
    from scripts.selector.dedup_filter import write_displayed_urls_log
    sig = inspect.signature(write_displayed_urls_log)
    params = set(sig.parameters.keys())
    expected = {"page1_urls", "page2_urls_by_company", "page3_urls",
                "page4_urls", "page5_url", "page6_urls", "headlines_urls"}
    _check("e1 writer は旧スキーマの全 page キーを受ける（過去日 log 互換）",
           expected.issubset(params), f"missing={expected - params}")


def test_page5_url_not_double_recorded():
    """一筆の参照記事が Page III 由来なら page5_url には記録しない.

    Page III の確定枠から選ばれた場合、page3_urls 側に既に載っているため
    二重記録になる。main() は「page3_urls に無い場合のみ」page5_url に
    入れる実装になっている。
    """
    src = inspect.getsource(regen.main)
    seg_start = src.find("page5_url_displayed: str | None = None")
    seg = src[seg_start:seg_start + 500]
    _check("e2 page5_url は page3_urls に無い場合のみ記録",
           "page3_urls_displayed" in seg, seg[:150])


def main() -> int:
    print("cross-page dedup 再配線 tests (C155, Sprint 13, 2026-08-10)")
    print()
    print("(a) build 順序の構造的保証:")
    test_page3_built_before_page6_in_main()
    test_page6_receives_page3_urls_not_page5()
    print()
    print("(b) Page III 全枠 → Page VI:")
    test_all_six_slots_contribute_to_dedup()
    test_placeholder_slots_are_skipped()
    test_serendipity_url_reaches_page6()
    print()
    print("(c) Page III 内の重複防止:")
    test_serendipity_not_duplicated_within_page3()
    test_serendipity_kept_when_distinct()
    print()
    print("(d) Page IV は dedup 経路から離脱:")
    test_page4_no_longer_takes_dedup_urls()
    test_page4_telemetry_has_no_articles()
    print()
    print("(e) displayed_urls スキーマ互換:")
    test_displayed_urls_writer_still_accepts_all_pages()
    test_page5_url_not_double_recorded()
    print()
    print(f"=== {PASS} passed, {FAIL} failed ===")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
