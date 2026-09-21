"""Web-Repo の Medium 毎日 union + 非採用候補ログ (C203, 2026-09-21).

背景
----
段階選定は「High で決まれば Medium を見ない」（``_STAGE_ORDER``）。
C202 の実測（2026-08-23〜09-21, 30 日）でウェブリポではこの前提が
成り立っていなかった。

    High 採用 19 日  平均 40.51 — 19 日すべてビジネスチャンス
    Med  採用  7 日  平均 43.23

Medium が回るのは High が threshold に一本も届かなかった日だけなのに、
それでも Medium のほうが高い。C203 で web_repo だけ union する。

このテストが固定すること
------------------------
1. web_repo は High が通っても Medium を引き、スコアが上なら Medium が勝つ
2. **他 2 社の挙動は変わらない**（High 通過時に Medium を引かない）
3. union 後に Medium を二重 fetch しない（コスト回帰）
4. 候補枯渇（union しても threshold 超えなし）で落ちない
5. 非採用候補がログに残る

Run::

    python3 -m tests.selector.test_page2_medium_union
"""

from __future__ import annotations

import json
import sys
import tempfile
from datetime import date
from pathlib import Path

from scripts.selector import page2

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


def _art(category: str, score: float, *, suffix: str, source: str = "src") -> dict:
    """page2_final_score を直接指定した候補（Step 1 を走らせない形）."""
    return {
        "url": f"https://example.test/{suffix}",
        "title": f"art {suffix}",
        "description": "d" * 200,
        "body": "",
        "source_name": source,
        "category": category,
        "final_score": 50.0,
        "managerial_implication": 7,
        "regulatory_signal": 5,
        "managerial_implication_reason": "stub",
        "regulatory_signal_reason": "stub",
        "page2_final_score": score,
    }


WR = "companies:Web-Repo"
CO = "companies:Cocolomi"
HE = "companies:Human Energy"


class _CountingFetcher:
    """priority ごとの呼び出し回数を数える fetcher."""

    def __init__(self, by_priority: dict[str, list[dict]] | None = None):
        self.by_priority = by_priority or {}
        self.calls: list[tuple[str, str]] = []

    def __call__(self, *, name_substring=None, category=None, priority=None, limit=8):
        self.calls.append((category, priority))
        pool = self.by_priority.get(priority, [])
        return [dict(a) for a in pool if a.get("category") == category]

    def count(self, category: str, priority: str) -> int:
        return sum(1 for c, p in self.calls if c == category and p == priority)


# ---------------------------------------------------------------------------
# (a) union が効く
# ---------------------------------------------------------------------------

def test_medium_wins_over_passing_high():
    """High が threshold を超えていても、Medium が上なら Medium が勝つ."""
    f = _CountingFetcher({"medium": [_art(WR, 46.0, suffix="wr-med", source="JFA")]})
    sel, _e, _c = page2.select_page2_articles(
        [_art(WR, 38.0, suffix="wr-high", source="ビジネスチャンス")],
        fetcher_fn=f, threshold=35.0,
    )
    s = sel["web_repo"]
    _check("a1 High 38.0 が通っても Medium 46.0 が勝つ",
           s.stage_used == "medium" and s.page2_final_score == 46.0,
           f"{s.stage_used} / {s.page2_final_score}")
    _check("a2 fallback_reason に union の旨が入る",
           bool(s.fallback_reason) and "union" in (s.fallback_reason or ""),
           str(s.fallback_reason))
    _check("a3 High 通過日にも Medium を fetch している",
           f.count(WR, "medium") == 1, f"{f.count(WR, 'medium')} 回")


def test_high_still_wins_when_better():
    """union しても High のほうが上なら High のまま（stage_used も high）."""
    f = _CountingFetcher({"medium": [_art(WR, 36.0, suffix="wr-med")]})
    sel, _e, _c = page2.select_page2_articles(
        [_art(WR, 44.0, suffix="wr-high")], fetcher_fn=f, threshold=35.0,
    )
    s = sel["web_repo"]
    _check("a4 High 44.0 > Medium 36.0 なら high のまま",
           s.stage_used == "high" and s.page2_final_score == 44.0,
           f"{s.stage_used} / {s.page2_final_score}")
    _check("a5 その場合 fallback_reason は None", s.fallback_reason is None)


def test_medium_not_fetched_twice():
    """union 経路で引いた後、Stage 2 で再 fetch しない（二重課金の回帰）."""
    f = _CountingFetcher({"medium": [_art(WR, 10.0, suffix="wr-med-low")]})
    sel, _e, _c = page2.select_page2_articles(
        [_art(WR, 12.0, suffix="wr-high-low")], fetcher_fn=f, threshold=35.0,
    )
    _check("a6 Medium fetch は 1 回だけ（union 後に再 fetch しない）",
           f.count(WR, "medium") == 1, f"{f.count(WR, 'medium')} 回")
    _check("a7 どちらも threshold 未満なら Stage 3 以降へ落ちる",
           sel["web_repo"].stage_used in ("reference", "cross_industry", "none"),
           sel["web_repo"].stage_used)


# ---------------------------------------------------------------------------
# (b) ★他 2 社に影響が無いこと
# ---------------------------------------------------------------------------

def test_other_companies_unchanged():
    """Cocolomi / Human Energy は High 通過時に Medium を引かない."""
    f = _CountingFetcher({"medium": [
        _art(CO, 99.0, suffix="co-med"),
        _art(HE, 99.0, suffix="he-med"),
        _art(WR, 99.0, suffix="wr-med"),
    ]})
    sel, _e, _c = page2.select_page2_articles(
        [_art(CO, 40.0, suffix="co-high"),
         _art(HE, 40.0, suffix="he-high"),
         _art(WR, 40.0, suffix="wr-high")],
        fetcher_fn=f, threshold=35.0,
    )
    _check("b1 Cocolomi は high のまま（Medium 99 点があっても無視）",
           sel["cocolomi"].stage_used == "high"
           and sel["cocolomi"].page2_final_score == 40.0,
           f"{sel['cocolomi'].stage_used} / {sel['cocolomi'].page2_final_score}")
    _check("b2 Human Energy も high のまま",
           sel["human_energy"].stage_used == "high"
           and sel["human_energy"].page2_final_score == 40.0,
           f"{sel['human_energy'].stage_used} / {sel['human_energy'].page2_final_score}")
    _check("b3 Cocolomi の Medium fetch は 0 回", f.count(CO, "medium") == 0,
           f"{f.count(CO, 'medium')} 回")
    _check("b4 Human Energy の Medium fetch は 0 回", f.count(HE, "medium") == 0,
           f"{f.count(HE, 'medium')} 回")
    _check("b5 Web-Repo だけ Medium が勝つ",
           sel["web_repo"].stage_used == "medium", sel["web_repo"].stage_used)


def test_union_set_is_web_repo_only():
    _check("b6 MEDIUM_UNION_COMPANY_KEYS は web_repo のみ",
           page2.MEDIUM_UNION_COMPANY_KEYS == frozenset({"web_repo"}),
           str(page2.MEDIUM_UNION_COMPANY_KEYS))


# ---------------------------------------------------------------------------
# (c) 候補枯渇
# ---------------------------------------------------------------------------

def test_no_candidates_at_all():
    """High も Medium も空でも落ちない（30 日で 4 日あった 'none' 経路）."""
    f = _CountingFetcher({})
    sel, _e, _c = page2.select_page2_articles([], fetcher_fn=f, threshold=35.0)
    _check("c1 候補ゼロでも例外にならず none に倒れる",
           sel["web_repo"].stage_used == "none", sel["web_repo"].stage_used)


def test_fetcher_none_is_safe():
    """fetcher_fn=None（既存の呼び出し形）で union 経路が壊れない."""
    sel, _e, _c = page2.select_page2_articles(
        [_art(WR, 44.0, suffix="wr-high")], fetcher_fn=None, threshold=35.0,
    )
    _check("c2 fetcher_fn=None でも high 選定が動く",
           sel["web_repo"].stage_used == "high", sel["web_repo"].stage_used)


def test_fetcher_raises_is_contained():
    class Boom(_CountingFetcher):
        def __call__(self, **kw):
            super().__call__(**kw)
            raise RuntimeError("boom")

    f = Boom()
    sel, errs, _c = page2.select_page2_articles(
        [_art(WR, 44.0, suffix="wr-high")], fetcher_fn=f, threshold=35.0,
    )
    _check("c3 Medium fetch が例外でも High 選定は生きる",
           sel["web_repo"].stage_used == "high", sel["web_repo"].stage_used)
    _check("c4 例外は EvaluationError に記録される",
           any("fetcher_error_medium" in e.error_type for e in errs))


# ---------------------------------------------------------------------------
# (d) 非採用候補ログ
# ---------------------------------------------------------------------------

def test_candidate_sink_records_losers():
    f = _CountingFetcher({"medium": [
        _art(WR, 46.0, suffix="wr-med-win", source="JFA"),
        _art(WR, 20.0, suffix="wr-med-lose", source="食品新聞"),
    ]})
    sink: dict[str, list[dict]] = {}
    page2.select_page2_articles(
        [_art(WR, 38.0, suffix="wr-high", source="ビジネスチャンス")],
        fetcher_fn=f, threshold=35.0, candidate_sink=sink,
    )
    rows = sink.get("web_repo", [])
    urls = {r["url"] for r in rows}
    _check("d1 High の非採用候補が残る",
           "https://example.test/wr-high" in urls, str(sorted(urls)))
    _check("d2 Medium の非採用候補も残る",
           "https://example.test/wr-med-lose" in urls)
    _check("d3 ソース名とスコアが入る",
           all(r.get("source_name") and r.get("page2_final_score") is not None
               for r in rows))
    _check("d4 stage が high / medium で区別される",
           {r["stage"] for r in rows} == {"high", "medium"},
           str({r["stage"] for r in rows}))


def test_candidate_log_written_with_selected_flag():
    res = page2.Page2Result(
        threshold=35.0, today=date(2026, 9, 21),
        selections={"web_repo": page2.CompanySelection(
            company_key="web_repo",
            article={"url": "https://example.test/win", "title": "w",
                     "source_name": "JFA", "category": WR},
            page2_final_score=46.0, morning_question="q",
            stage_used="medium", threshold_passed=True, fallback_reason=None,
        )},
        candidates={"web_repo": [
            {"url": "https://example.test/win", "source_name": "JFA",
             "stage": "medium", "page2_final_score": 46.0},
            {"url": "https://example.test/lose", "source_name": "ビジネスチャンス",
             "stage": "high", "page2_final_score": 38.0},
        ]},
    )
    with tempfile.TemporaryDirectory() as td:
        orig = page2.LOG_DIR
        try:
            page2.LOG_DIR = Path(td)
            path = page2.write_page2_log(res)
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        finally:
            page2.LOG_DIR = orig
    cl = data.get("candidate_log", {}).get("Web-Repo", [])
    _check("d5 candidate_log がファイルに書かれる", len(cl) == 2, f"{len(cl)} 件")
    _check("d6 採用フラグが立つ",
           bool(cl) and cl[0]["selected_for_page2"] is True
           and cl[1]["selected_for_page2"] is False,
           str([r.get("selected_for_page2") for r in cl]))
    _check("d7 スコア降順で並ぶ",
           bool(cl) and cl[0]["page2_final_score"] >= cl[-1]["page2_final_score"])
    _check("d8 負けたビジネスチャンスの点が残る",
           any(r["source_name"] == "ビジネスチャンス"
               and r["page2_final_score"] == 38.0 for r in cl))


def test_top_n_cap():
    many = [_art(WR, float(i), suffix=f"m{i}") for i in range(40)]
    sink: dict[str, list[dict]] = {}
    page2._record_candidates(sink, "web_repo", "medium", many)
    n = len(sink["web_repo"])
    _check(f"d9 上位 {page2.CANDIDATE_LOG_TOP_N} 件に絞られる",
           n == page2.CANDIDATE_LOG_TOP_N, f"{n} 件")
    _check("d10 残るのはスコア上位側",
           sink["web_repo"][0]["page2_final_score"] == 39.0,
           str(sink["web_repo"][0]["page2_final_score"]))


def main() -> int:
    print("C203: Web-Repo Medium union + 非採用候補ログ\n")
    print("(a) union が効く:")
    test_medium_wins_over_passing_high()
    test_high_still_wins_when_better()
    test_medium_not_fetched_twice()
    print()
    print("(b) ★他 2 社に影響が無い:")
    test_other_companies_unchanged()
    test_union_set_is_web_repo_only()
    print()
    print("(c) 候補枯渇・異常系:")
    test_no_candidates_at_all()
    test_fetcher_none_is_safe()
    test_fetcher_raises_is_contained()
    print()
    print("(d) 非採用候補ログ:")
    test_candidate_sink_records_losers()
    test_candidate_log_written_with_selected_flag()
    test_top_n_cap()
    print()
    print(f"=== {PASS} passed, {FAIL} failed ===")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
