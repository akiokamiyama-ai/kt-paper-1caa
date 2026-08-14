"""到達不能ソースの棚卸しと週次プローブ (C163, Sprint 13, 2026-08-14).

背景
----
経産省 / JFTC / ダ・ヴィンチWeb / ナタリー音楽 の 4 件は、フィード自体は
生きている（ローカルからは 200 OK）が GHA runner の IP からは 403/405 が
返る。毎朝叩いても必ず失敗し、ログに 6-10 件のノイズを出して新規の障害を
見えにくくしていた（8/14 の Reuters 503 が埋もれた）。

日次 fetch から外すが、「静かに諦める」と復旧を見落とす（C156 の教訓）ため
週 1 回だけプローブする。

Tests:
  a) UNREACHABLE_MARKER の判定と、恒久的に死んだ ❌ との区別
  b) marker 付きソースは fetch_method を保持する（プローブで正しく dispatch）
  c) select_sources が日次では除外、プローブ日には含める
  d) 実データ: 対象 4 件が正しく分類されている
  e) プローブ曜日の判定

Run::

    python3 -m tests.test_unreachable_sources
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

from scripts.fetch import UNREACHABLE_PROBE_WEEKDAY, is_probe_day, select_sources
from scripts.lib.source import (
    UNREACHABLE_MARKER,
    FetchMethod,
    Status,
    load_all_sources,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SOURCES_DIR = PROJECT_ROOT / "sources"

# C163 で到達不能マークを付けた 4 件
EXPECTED_UNREACHABLE = {
    "経済産業省ニュースリリース",
    "公正取引委員会 報道発表",
    "ダ・ヴィンチWeb（KADOKAWA）",
    "ナタリー音楽",
}

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


def _sources():
    return load_all_sources(SOURCES_DIR)


# ---------------------------------------------------------------------------
# (a) marker 判定 / 恒久死との区別
# ---------------------------------------------------------------------------

def test_marker_constant():
    _check("a1 UNREACHABLE_MARKER が定義されている",
           UNREACHABLE_MARKER == "BLOCKED_RUNNER_IP", UNREACHABLE_MARKER)


def test_unreachable_requires_marker():
    """❌ だけでは is_unreachable にならない（恒久死と区別する）."""
    srcs = _sources()
    failed = [s for s in srcs if s.status == Status.FAILED]
    unreachable = [s for s in srcs if s.is_unreachable]
    permanently_dead = [s for s in failed if not s.is_unreachable]
    _check("a2 ❌ のうち marker 付きだけが is_unreachable",
           len(unreachable) < len(failed),
           f"❌={len(failed)}, unreachable={len(unreachable)}")
    _check("a3 恒久的に死んだ ❌ も残っている（区別できている）",
           len(permanently_dead) > 0,
           f"{[s.name for s in permanently_dead][:3]}")


def test_permanently_dead_are_blocked_method():
    """marker 無しの ❌ は従来どおり FetchMethod.BLOCKED（driver を呼ばない）."""
    bad = [
        s.name for s in _sources()
        if s.status == Status.FAILED and not s.is_unreachable
        and s.fetch_method != FetchMethod.BLOCKED
    ]
    _check("a4 恒久死 ❌ は BLOCKED のまま", not bad, f"got {bad}")


# ---------------------------------------------------------------------------
# (b) marker 付きは fetch_method を保持
# ---------------------------------------------------------------------------

def test_unreachable_keeps_real_fetch_method():
    """プローブ日に正しい driver へ dispatch するため、方法を潰さない."""
    bad = [
        (s.name, s.fetch_method.value) for s in _sources()
        if s.is_unreachable and s.fetch_method == FetchMethod.BLOCKED
    ]
    _check("b1 到達不能ソースは BLOCKED に潰されない（rss/html を保持）",
           not bad, f"got {bad}")


def test_unreachable_has_endpoint():
    """プローブに使う URL が残っていること."""
    bad = [s.name for s in _sources() if s.is_unreachable and not (s.rss_url or s.url)]
    _check("b2 到達不能ソースにも取得先 URL が残っている", not bad, f"got {bad}")


# ---------------------------------------------------------------------------
# (c) select_sources の日次 / プローブ日
# ---------------------------------------------------------------------------

def _selected_names(probe: bool, include_html: bool = True) -> set[str]:
    sel = select_sources(
        _sources(), category=None, priority=None, name_substring=None,
        include_html=include_html, probe_unreachable=probe,
    )
    return {s.name for s in sel}


def test_daily_excludes_unreachable():
    names = _selected_names(probe=False)
    leaked = EXPECTED_UNREACHABLE & names
    _check("c1 日次 fetch では到達不能ソースを選ばない（ログノイズの源を断つ）",
           not leaked, f"leaked={sorted(leaked)}")


def test_probe_day_includes_unreachable():
    names = _selected_names(probe=True)
    missing = EXPECTED_UNREACHABLE - names
    _check("c2 プローブ日には全 4 件が選ばれる（復旧の見落とし防止）",
           not missing, f"missing={sorted(missing)}")


def test_probe_day_adds_only_unreachable():
    """プローブ日でも他のソース選択は変わらない."""
    daily = _selected_names(probe=False)
    probe = _selected_names(probe=True)
    _check("c3 プローブ日の増分は到達不能ソースのみ",
           probe - daily == EXPECTED_UNREACHABLE,
           f"diff={sorted(probe - daily)}")
    _check("c4 プローブ日に減るソースは無い", not (daily - probe))


def test_default_probe_flag_follows_weekday():
    """probe_unreachable 未指定なら曜日で自動判定."""
    import inspect
    sig = inspect.signature(select_sources)
    _check("c5 probe_unreachable の既定は None（曜日判定に委ねる）",
           sig.parameters["probe_unreachable"].default is None)


# ---------------------------------------------------------------------------
# (d) 実データの分類
# ---------------------------------------------------------------------------

def test_expected_four_are_marked():
    got = {s.name for s in _sources() if s.is_unreachable}
    _check("d1 C163 で棚卸しした 4 件が到達不能マーク済",
           got == EXPECTED_UNREACHABLE, f"got={sorted(got)}")


def test_each_has_documented_reason():
    """fetch_status に確認日 / C 番号が書かれていること（判断根拠の明記）."""
    bad = []
    for s in _sources():
        if not s.is_unreachable:
            continue
        note = s.fetch_status_note
        if "2026-" not in note or "C163" not in note:
            bad.append((s.name, note[:40]))
    _check("d2 各ソースに確認日と C 番号が記録されている", not bad, f"got {bad}")


def test_jftc_documents_c130_history():
    """JFTC は C130 の経緯（UA override で一時回避 → 再発）を明記する."""
    jftc = [s for s in _sources() if s.name == "公正取引委員会 報道発表"]
    _check("d3 JFTC のソース定義が存在", len(jftc) == 1)
    if not jftc:
        return
    md = (SOURCES_DIR / "companies.md").read_text(encoding="utf-8")
    i = md.find("#### 3. 公正取引委員会 報道発表")
    block = md[i:i + 1800]
    _check("d4 JFTC ブロックに C130 の経緯が書かれている",
           "C130" in block and "Akamai" in block)
    _check("d5 UA 再変更を推奨しない旨が書かれている", "推奨しない" in block)


# ---------------------------------------------------------------------------
# (e) プローブ曜日
# ---------------------------------------------------------------------------

def test_probe_weekday():
    _check("e1 プローブは週 1 回（曜日固定）",
           0 <= UNREACHABLE_PROBE_WEEKDAY <= 6)
    hits = [d for d in range(1, 8)
            if is_probe_day(date(2026, 8, 16) + __import__("datetime").timedelta(days=d))]
    _check("e2 任意の 7 日間でちょうど 1 日だけプローブ日",
           len(hits) == 1, f"got {len(hits)} days")


def main() -> int:
    print("到達不能ソースの棚卸し tests (C163, Sprint 13, 2026-08-14)")
    print()
    print("(a) marker 判定 / 恒久死との区別:")
    test_marker_constant()
    test_unreachable_requires_marker()
    test_permanently_dead_are_blocked_method()
    print()
    print("(b) fetch_method の保持:")
    test_unreachable_keeps_real_fetch_method()
    test_unreachable_has_endpoint()
    print()
    print("(c) 日次 / 週次プローブの選択:")
    test_daily_excludes_unreachable()
    test_probe_day_includes_unreachable()
    test_probe_day_adds_only_unreachable()
    test_default_probe_flag_follows_weekday()
    print()
    print("(d) 実データの分類:")
    test_expected_four_are_marked()
    test_each_has_documented_reason()
    test_jftc_documents_c130_history()
    print()
    print("(e) プローブ曜日:")
    test_probe_weekday()
    print()
    print(f"=== {PASS} passed, {FAIL} failed ===")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
