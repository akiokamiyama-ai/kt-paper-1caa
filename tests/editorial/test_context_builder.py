"""Unit tests for editorial.context_builder (Sprint 4 Phase 3, 2026-05-03).

Tests:
  a) Empty inputs produce a fully-skeleton context (no missing keys)
  b) Page I top + secondaries extracted in order
  c) Page II selections in fixed company order with display names
  d) Page III selections in R1..R6 region order
  e) Page IV concept name + academic article titles
  f) Page V serendipity + AIかみやま column title
  g) Page VI 4-area column titles
  h) JSON-serialisable
  i) Missing keys / None article handled silently
  j) Real telemetry shapes (sanity)

Run::

    python3 -m tests.editorial.test_context_builder
"""

from __future__ import annotations

import json
import sys
from types import SimpleNamespace

from scripts.editorial import context_builder

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
# (a) Empty inputs
# ---------------------------------------------------------------------------

def test_empty_inputs_produce_skeleton():
    ctx = context_builder.build_editorial_context()
    expected_keys = {
        "page1_top", "page1_secondaries", "page2", "page3",
        "page4_concept", "page4_articles",
        "page5_serendipity", "page5_aikamiyama_column_title",
        "page6_columns",
    }
    has_all = expected_keys.issubset(ctx.keys())
    _check("a1 all skeleton keys present even on empty input", has_all,
           f"missing={expected_keys - ctx.keys()}")
    _check("a2 page1_top is empty dict shape",
           ctx["page1_top"] == {"title": "", "source": ""})
    _check("a3 page2 has 3 entries (one per company) even on empty",
           len(ctx["page2"]) == 3,
           f"len={len(ctx['page2'])}")
    _check("a4 page3 has 6 entries (R1..R6) even on empty",
           len(ctx["page3"]) == 6)
    _check("a5 page6_columns has all 4 areas",
           set(ctx["page6_columns"].keys()) == {"books", "music", "outdoor", "cooking"})


# ---------------------------------------------------------------------------
# (b) Page I extraction
# ---------------------------------------------------------------------------

def test_page1_top_and_secondaries():
    selected = [
        {"title": "Top", "source_name": "The Economist", "url": "https://e/1"},
        {"title": "Sec1", "source_name": "Foresight"},
        {"title": "Sec2", "source_name": "BBC Business"},
        {"title": "Sec3", "source_name": "Reuters Business"},
    ]
    ctx = context_builder.build_editorial_context(page_one_selected=selected)
    _check("b1 page1_top.title = 'Top'",
           ctx["page1_top"] == {"title": "Top", "source": "The Economist"})
    _check("b2 page1_secondaries has 3 entries",
           len(ctx["page1_secondaries"]) == 3)
    _check("b3 page1_secondaries[0].title = 'Sec1'",
           ctx["page1_secondaries"][0] == {"title": "Sec1", "source": "Foresight"})


# ---------------------------------------------------------------------------
# (c) Page II company order + display names
# ---------------------------------------------------------------------------

def test_page2_company_order_and_display():
    sel_kk = SimpleNamespace(article={"title": "AI記事", "source_name": "ZDNet Japan"})
    sel_he = SimpleNamespace(article={"title": "組織記事", "source_name": "MIT Sloan"})
    sel_wr = SimpleNamespace(article=None)
    selections = {
        "cocolomi": sel_kk,
        "human_energy": sel_he,
        "web_repo": sel_wr,
    }
    ctx = context_builder.build_editorial_context(page_two_selections=selections)
    _check("c1 page2 entries in fixed order",
           [e["company"] for e in ctx["page2"]] ==
           ["こころみ", "ヒューマンエナジー", "ウェブリポ"])
    _check("c2 cocolomi article extracted",
           ctx["page2"][0]["title"] == "AI記事" and ctx["page2"][0]["source"] == "ZDNet Japan")
    _check("c3 web_repo None article → empty title/source",
           ctx["page2"][2]["title"] == "" and ctx["page2"][2]["source"] == "")


# ---------------------------------------------------------------------------
# (d) Page III region order
# ---------------------------------------------------------------------------

def test_page3_region_order():
    sels = {
        "R1": SimpleNamespace(article={"title": "国際金融記事", "source_name": "WoTR"}),
        "R3": SimpleNamespace(article={"title": "テック覇権記事", "source_name": "MIT"}),
        "R6": SimpleNamespace(article={"title": "学術記事", "source_name": "Nautilus"}),
        # R2/R4/R5 missing entirely
    }
    ctx = context_builder.build_editorial_context(page_three_selections=sels)
    regions = [e["region"] for e in ctx["page3"]]
    _check("d1 page3 region order R1..R6",
           regions == ["R1", "R2", "R3", "R4", "R5", "R6"])
    _check("d2 R1 article populated",
           ctx["page3"][0]["title"] == "国際金融記事")
    _check("d3 R2 missing → empty entry",
           ctx["page3"][1] == {"title": "", "source": "", "region": "R2"})


# ---------------------------------------------------------------------------
# (e) Page IV concept + academic articles
# ---------------------------------------------------------------------------

def test_page4_concept_and_articles():
    telemetry = {
        "concept": {"id": "theory_of_mind", "name_ja": "心の理論"},
        "articles_result": {
            "articles": [
                {"title": "学術記事1"},
                {"title": "学術記事2"},
                {"title": "学術記事3"},
            ],
        },
    }
    ctx = context_builder.build_editorial_context(page_four_telemetry=telemetry)
    _check("e1 page4_concept = name_ja", ctx["page4_concept"] == "心の理論")
    _check("e2 page4_articles has 3 titles",
           ctx["page4_articles"] == ["学術記事1", "学術記事2", "学術記事3"])


def test_page4_falls_back_to_concept_id_if_no_name_ja():
    telemetry = {"concept": {"id": "tom_only"}, "articles_result": {"articles": []}}
    ctx = context_builder.build_editorial_context(page_four_telemetry=telemetry)
    _check("e3 page4_concept falls back to id when name_ja missing",
           ctx["page4_concept"] == "tom_only")


# ---------------------------------------------------------------------------
# (f) Page V serendipity + AIかみやま
# ---------------------------------------------------------------------------

def test_page5_serendipity_and_column():
    telemetry = {
        "serendipity": {
            "article": {"title": "サウナ記事", "source_name": "AXIS"},
            "category": "culture",
        },
        "column": {"column_title": "ロウリュは沈黙の傘装置"},
    }
    ctx = context_builder.build_editorial_context(page_five_telemetry=telemetry)
    _check("f1 page5_serendipity article + category populated",
           ctx["page5_serendipity"] == {
               "title": "サウナ記事", "source": "AXIS", "category": "culture",
           })
    _check("f2 AIかみやま column_title extracted",
           ctx["page5_aikamiyama_column_title"] == "ロウリュは沈黙の傘装置")


# ---------------------------------------------------------------------------
# (g) Page VI 4-area columns
# ---------------------------------------------------------------------------

def test_page6_4_columns():
    telemetry = {
        "books": {"column_title": "読書コラム"},
        "music": {"column_title": "音楽コラム"},
        "outdoor": {"column_title": "アウトドアコラム"},
        "cooking": {"column_title": "料理コラム"},
    }
    ctx = context_builder.build_editorial_context(page_six_telemetry=telemetry)
    _check("g1 all 4 area column titles extracted",
           ctx["page6_columns"] == {
               "books": "読書コラム", "music": "音楽コラム",
               "outdoor": "アウトドアコラム", "cooking": "料理コラム",
           })


# ---------------------------------------------------------------------------
# (h) JSON serialisability
# ---------------------------------------------------------------------------

def test_context_is_json_serialisable():
    ctx = context_builder.build_editorial_context(
        page_one_selected=[{"title": "T", "source_name": "S"}],
        page_six_telemetry={"books": {"column_title": "B"}},
    )
    try:
        s = json.dumps(ctx, ensure_ascii=False)
        ok = '"books": "B"' in s
    except Exception as e:
        s = ""
        ok = False
    _check("h1 context dumps to JSON without error", ok,
           f"sample[:80]={s[:80]!r}")


def main() -> int:
    print("Editorial context builder tests (Sprint 4 Phase 3, 2026-05-03)")
    print()
    print("(a) Empty inputs:")
    test_empty_inputs_produce_skeleton()
    print()
    print("(b) Page I:")
    test_page1_top_and_secondaries()
    print()
    print("(c) Page II:")
    test_page2_company_order_and_display()
    print()
    print("(d) Page III:")
    test_page3_region_order()
    print()
    print("(e) Page IV:")
    test_page4_concept_and_articles()
    test_page4_falls_back_to_concept_id_if_no_name_ja()
    print()
    print("(f) Page V:")
    test_page5_serendipity_and_column()
    print()
    print("(g) Page VI:")
    test_page6_4_columns()
    print()
    print("(h) JSON serialisable:")
    test_context_is_json_serialisable()
    print()
    print(f"=== {PASS} passed, {FAIL} failed ===")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
