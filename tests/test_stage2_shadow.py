"""Unit tests for stage2_shadow.py (C85 Sub-Step 6-7).

Phase B Step 4: shadow mode 経路の dispatch / shadow log の生成 / 採用結果が
legacy であることを検証する。**LLM 呼び出しを行わない** ため、内部の
``run_stage2`` を mock + fixture Stage2Result で動作を観察する。

Run::

    python3 -m tests.test_stage2_shadow
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

from scripts.selector import stage2 as s2_mod
from scripts.selector import stage2_shadow as shw
from scripts.selector.stage2 import LayerConfig, Stage2Result

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
# (a) get_stage2_mode
# ---------------------------------------------------------------------------

def test_default_mode_is_legacy():
    os.environ.pop(shw.ENV_MODE, None)
    _check("a1 環境変数なし → 'legacy'", shw.get_stage2_mode() == "legacy")


def test_mode_shadow():
    os.environ[shw.ENV_MODE] = "shadow"
    try:
        _check("a2 TRIBUNE_STAGE2_MODE=shadow → 'shadow'",
               shw.get_stage2_mode() == "shadow")
    finally:
        os.environ.pop(shw.ENV_MODE, None)


def test_mode_layered():
    os.environ[shw.ENV_MODE] = "layered"
    try:
        _check("a3 TRIBUNE_STAGE2_MODE=layered → 'layered'",
               shw.get_stage2_mode() == "layered")
    finally:
        os.environ.pop(shw.ENV_MODE, None)


def test_mode_invalid_falls_back():
    """不正値は legacy fallback + stderr 警告."""
    import io
    saved = sys.stderr
    sys.stderr = io.StringIO()
    os.environ[shw.ENV_MODE] = "bogus"
    try:
        result = shw.get_stage2_mode()
    finally:
        os.environ.pop(shw.ENV_MODE, None)
        captured = sys.stderr.getvalue()
        sys.stderr = saved
    _check("a4 不正値 → 'legacy' fallback + 警告",
           result == "legacy" and "WARN" in captured)


def test_mode_case_insensitive():
    os.environ[shw.ENV_MODE] = "SHADOW"
    try:
        _check("a5 大文字 'SHADOW' でも 'shadow'",
               shw.get_stage2_mode() == "shadow")
    finally:
        os.environ.pop(shw.ENV_MODE, None)


def test_mode_shadow_page1_only_recognized():
    """C86: 新モード 'shadow_page1_only' が VALID_MODES に含まれる."""
    os.environ[shw.ENV_MODE] = "shadow_page1_only"
    try:
        _check("a6 TRIBUNE_STAGE2_MODE=shadow_page1_only → 認識",
               shw.get_stage2_mode() == "shadow_page1_only"
               and "shadow_page1_only" in shw.VALID_MODES)
    finally:
        os.environ.pop(shw.ENV_MODE, None)


def test_shadow_page1_only_callers_set():
    """C86: page1_master のみが shadow 対象."""
    _check("a7 SHADOW_PAGE1_ONLY_CALLERS = {'page1_master'}",
           shw.SHADOW_PAGE1_ONLY_CALLERS == frozenset({"page1_master"}))


def test_mode_layered_page1_recognized():
    """C93: 新モード 'layered_page1' が VALID_MODES に含まれる."""
    os.environ[shw.ENV_MODE] = "layered_page1"
    try:
        _check("a8 TRIBUNE_STAGE2_MODE=layered_page1 → 認識",
               shw.get_stage2_mode() == "layered_page1"
               and "layered_page1" in shw.VALID_MODES)
    finally:
        os.environ.pop(shw.ENV_MODE, None)


def test_layered_page1_callers_set():
    """C93: page1_master のみが layered 対象."""
    _check("a9 LAYERED_PAGE1_CALLERS = {'page1_master'}",
           shw.LAYERED_PAGE1_CALLERS == frozenset({"page1_master"}))


# ---------------------------------------------------------------------------
# (b) run_stage2_with_mode dispatch
# ---------------------------------------------------------------------------

def _stub_result(model: str, n_urls: int = 0, cost: float = 0.0) -> Stage2Result:
    """Build a minimal Stage2Result fixture (no LLM call)."""
    r = Stage2Result(model=model)
    r.cost_usd = cost
    for i in range(n_urls):
        r.evaluations_by_url[f"https://x/{i}"] = {
            "美意識1": 7, "美意識3": 8, "美意識5": 5,
            "美意識6": 4, "美意識8": 3,
            "美意識2_machine": 27, "final_score": 50 + i,
            "model": model,
        }
    return r


def _patch_run_stage2(replacement):
    """Monkey-patch run_stage2 in both stage2 and stage2_shadow modules."""
    orig_s2 = s2_mod.run_stage2
    orig_shw = shw.run_stage2
    s2_mod.run_stage2 = replacement
    shw.run_stage2 = replacement
    return orig_s2, orig_shw


def _restore_run_stage2(orig_s2, orig_shw):
    s2_mod.run_stage2 = orig_s2
    shw.run_stage2 = orig_shw


def test_dispatch_legacy_mode():
    calls: list[dict] = []

    def fake(articles, *, layer_config=None, caller="page1_master", **kw):
        calls.append({"layer_config": layer_config, "caller": caller})
        return _stub_result("claude-sonnet-4-6")

    orig = _patch_run_stage2(fake)
    try:
        r = shw.run_stage2_with_mode([{"url": "x"}], caller="page1_master", mode="legacy")
    finally:
        _restore_run_stage2(*orig)

    _check(
        "b1 mode='legacy' → run_stage2 1 回呼び出し + layer_config=None",
        len(calls) == 1 and calls[0]["layer_config"] is None,
    )


def test_dispatch_layered_mode():
    calls: list[dict] = []

    def fake(articles, *, layer_config=None, caller="page1_master", **kw):
        calls.append({"layer_config": layer_config, "caller": caller})
        return _stub_result(
            f"layered(claude-haiku-4-5/claude-sonnet-4-6)"
        )

    orig = _patch_run_stage2(fake)
    try:
        r = shw.run_stage2_with_mode([{"url": "x"}], caller="page3", mode="layered")
    finally:
        _restore_run_stage2(*orig)

    _check(
        "b2 mode='layered' → run_stage2 1 回 + LayerConfig(enabled=True)",
        len(calls) == 1
        and calls[0]["layer_config"] is not None
        and calls[0]["layer_config"].enabled is True
        and calls[0]["caller"] == "page3",
    )


def test_dispatch_shadow_mode_runs_both_and_returns_legacy():
    calls: list[dict] = []

    def fake(articles, *, layer_config=None, caller="page1_master", **kw):
        is_layered = layer_config is not None and layer_config.enabled
        calls.append({"is_layered": is_layered, "caller": caller})
        model = (
            "layered(claude-haiku-4-5/claude-sonnet-4-6)"
            if is_layered else "claude-sonnet-4-6"
        )
        # legacy / layered で違う cost を返して採用判別を可視化
        return _stub_result(model, n_urls=3, cost=(0.99 if is_layered else 0.11))

    orig = _patch_run_stage2(fake)
    with tempfile.TemporaryDirectory() as td:
        shadow_path = Path(td) / "stage2_shadow_test.json"
        try:
            r = shw.run_stage2_with_mode(
                [{"url": "x"}], caller="page1_master",
                mode="shadow", shadow_log_path=shadow_path,
            )
        finally:
            _restore_run_stage2(*orig)

        _check(
            "b3 mode='shadow' → run_stage2 2 回呼び出し（legacy + layered）",
            len(calls) == 2
            and not calls[0]["is_layered"]
            and calls[1]["is_layered"],
        )
        _check(
            "b4 mode='shadow' → 戻り値は **legacy** 結果（layered ではない）",
            "layered" not in r.model and r.cost_usd == 0.11,
            f"got model={r.model!r} cost={r.cost_usd}",
        )
        _check(
            "b5 mode='shadow' → shadow log が生成される",
            shadow_path.exists(),
        )

        # log 構造の検証
        log = json.loads(shadow_path.read_text(encoding="utf-8"))
        _check(
            "b6 shadow log: date + callers キー",
            "date" in log and "callers" in log and "page1_master" in log["callers"],
        )
        entry = log["callers"]["page1_master"]
        _check(
            "b7 shadow log entry: legacy + layered cost 両方記録",
            entry["legacy_cost_usd"] == 0.11
            and entry["layered_cost_usd"] == 0.99,
        )
        _check(
            "b8 shadow log entry: overlap_count + overlap_ratio あり",
            "overlap_count" in entry and "overlap_ratio" in entry,
        )


# ---------------------------------------------------------------------------
# (b2) shadow_page1_only (C86)
# ---------------------------------------------------------------------------

def test_dispatch_shadow_page1_only_for_master_caller():
    """C86: shadow_page1_only + caller='page1_master' → shadow 動作（2 回実行）."""
    calls: list[dict] = []

    def fake(articles, *, layer_config=None, caller="page1_master", **kw):
        is_layered = layer_config is not None and layer_config.enabled
        calls.append({"is_layered": is_layered, "caller": caller})
        model = (
            "layered(claude-haiku-4-5/claude-sonnet-4-6)"
            if is_layered else "claude-sonnet-4-6"
        )
        return _stub_result(model, n_urls=2, cost=(0.5 if is_layered else 0.3))

    orig = _patch_run_stage2(fake)
    with tempfile.TemporaryDirectory() as td:
        shadow_path = Path(td) / "stage2_shadow.json"
        try:
            r = shw.run_stage2_with_mode(
                [{"url": "x"}], caller="page1_master",
                mode="shadow_page1_only", shadow_log_path=shadow_path,
            )
        finally:
            _restore_run_stage2(*orig)

        _check(
            "b9 shadow_page1_only + caller=page1_master → run_stage2 2 回",
            len(calls) == 2
            and not calls[0]["is_layered"]
            and calls[1]["is_layered"],
        )
        _check(
            "b10 shadow_page1_only + caller=page1_master → 採用は legacy",
            "layered" not in r.model and r.cost_usd == 0.3,
        )
        _check(
            "b11 shadow_page1_only + caller=page1_master → shadow log 生成",
            shadow_path.exists(),
        )


def test_dispatch_shadow_page1_only_for_other_caller():
    """C86: shadow_page1_only + caller='page3' → legacy 動作（1 回のみ）."""
    calls: list[dict] = []

    def fake(articles, *, layer_config=None, caller="page1_master", **kw):
        is_layered = layer_config is not None and layer_config.enabled
        calls.append({"is_layered": is_layered, "caller": caller})
        return _stub_result("claude-sonnet-4-6", n_urls=1, cost=0.1)

    orig = _patch_run_stage2(fake)
    with tempfile.TemporaryDirectory() as td:
        shadow_path = Path(td) / "stage2_shadow.json"
        try:
            r = shw.run_stage2_with_mode(
                [{"url": "x"}], caller="page3",
                mode="shadow_page1_only", shadow_log_path=shadow_path,
            )
        finally:
            _restore_run_stage2(*orig)

        _check(
            "b12 shadow_page1_only + caller=page3 → run_stage2 1 回のみ（legacy 経路）",
            len(calls) == 1 and not calls[0]["is_layered"],
        )
        _check(
            "b13 shadow_page1_only + caller=page3 → shadow log 生成しない",
            not shadow_path.exists(),
        )


def test_dispatch_shadow_page1_only_for_page4_page5_page6():
    """C86: page4/5/6 もすべて legacy 経路（pre_evaluated 経由でほぼ free rider）."""
    results = []
    for caller in ("page4", "page5", "page6", "page2"):
        calls = []

        def fake(articles, *, layer_config=None, caller=caller, **kw):
            is_layered = layer_config is not None and layer_config.enabled
            calls.append(is_layered)
            return _stub_result("claude-sonnet-4-6", cost=0.05)

        orig = _patch_run_stage2(fake)
        try:
            shw.run_stage2_with_mode(
                [{"url": "x"}], caller=caller, mode="shadow_page1_only",
            )
        finally:
            _restore_run_stage2(*orig)
        results.append((caller, len(calls), calls[0] if calls else None))

    _check(
        "b14 shadow_page1_only + page4/5/6/2 すべて legacy（1 回のみ、is_layered=False）",
        all(n == 1 and is_l is False for _, n, is_l in results),
        f"got {results}",
    )


# ---------------------------------------------------------------------------
# (b4) C93 layered_page1 (本番切替モード)
# ---------------------------------------------------------------------------

def test_dispatch_layered_page1_for_master_caller():
    """C93: layered_page1 + caller='page1_master' → layered 1 回（採用 = layered）."""
    calls: list[dict] = []

    def fake(articles, *, layer_config=None, caller="page1_master", **kw):
        is_layered = layer_config is not None and layer_config.enabled
        calls.append({"is_layered": is_layered, "caller": caller})
        model = (
            "layered(claude-haiku-4-5/claude-sonnet-4-6)"
            if is_layered else "claude-sonnet-4-6"
        )
        return _stub_result(model, n_urls=2, cost=(0.10 if is_layered else 0.40))

    orig = _patch_run_stage2(fake)
    with tempfile.TemporaryDirectory() as td:
        shadow_path = Path(td) / "stage2_shadow.json"
        try:
            r = shw.run_stage2_with_mode(
                [{"url": "x"}], caller="page1_master",
                mode="layered_page1", shadow_log_path=shadow_path,
            )
        finally:
            _restore_run_stage2(*orig)

        _check(
            "b19 layered_page1 + caller=page1_master → run_stage2 1 回（layered）",
            len(calls) == 1 and calls[0]["is_layered"] is True,
        )
        _check(
            "b20 layered_page1 + caller=page1_master → 採用は layered（shadow ではなく本番切替）",
            "layered" in r.model and r.cost_usd == 0.10,
        )
        _check(
            "b21 layered_page1 + caller=page1_master → shadow log は生成しない",
            not shadow_path.exists(),
        )


def test_dispatch_layered_page1_for_other_callers():
    """C93: layered_page1 + page3/4/5/6/2 → すべて legacy 1 回のみ."""
    results = []
    for caller in ("page3", "page4", "page5", "page6", "page2"):
        calls = []

        def fake(articles, *, layer_config=None, caller=caller, **kw):
            is_layered = layer_config is not None and layer_config.enabled
            calls.append(is_layered)
            return _stub_result("claude-sonnet-4-6", cost=0.05)

        orig = _patch_run_stage2(fake)
        try:
            shw.run_stage2_with_mode(
                [{"url": "x"}], caller=caller, mode="layered_page1",
            )
        finally:
            _restore_run_stage2(*orig)
        results.append((caller, len(calls), calls[0] if calls else None))

    _check(
        "b22 layered_page1 + page3/4/5/6/2 すべて legacy（1 回のみ、is_layered=False）",
        all(n == 1 and is_l is False for _, n, is_l in results),
        f"got {results}",
    )


# ---------------------------------------------------------------------------
# (b3) C88 JST date anchor
# ---------------------------------------------------------------------------

def test_jst_today_returns_date_object():
    """C88: _jst_today() は date 型を返す."""
    import datetime as _dt
    today = shw._jst_today()
    _check("b15 _jst_today() returns datetime.date", isinstance(today, _dt.date))


def test_jst_today_uses_tokyo_timezone():
    """C88: UTC が前日でも JST 換算で当日を返す（UTC 23:50 = JST 翌 08:50）."""
    import datetime as _dt
    from unittest.mock import patch

    # UTC 2026-06-15 23:50 = JST 2026-06-16 08:50。_jst_today() は 6/16 を返すべき。
    fixed_utc = _dt.datetime(2026, 6, 15, 23, 50, tzinfo=_dt.timezone.utc)

    class _FakeDT(_dt.datetime):
        @classmethod
        def now(cls, tz=None):
            if tz is None:
                return fixed_utc.replace(tzinfo=None)
            return fixed_utc.astimezone(tz)

    with patch.object(shw, "datetime", _FakeDT):
        result = shw._jst_today()
    _check(
        "b16 UTC 6/15 23:50 → JST 換算で 6/16 を返す",
        result == _dt.date(2026, 6, 16),
        f"got {result}",
    )


def test_shadow_log_path_uses_jst_date():
    """C88: shadow log ファイル名 / 内部 date フィールドは JST 日付."""
    import datetime as _dt
    from unittest.mock import patch

    # UTC 6/15 20:38（= 6/16 朝 cron 起動の実例、JST 05:38）
    fixed_utc = _dt.datetime(2026, 6, 15, 20, 38, tzinfo=_dt.timezone.utc)

    class _FakeDT(_dt.datetime):
        @classmethod
        def now(cls, tz=None):
            if tz is None:
                return fixed_utc.replace(tzinfo=None)
            return fixed_utc.astimezone(tz)

    legacy = _stub_result("claude-sonnet-4-6", n_urls=3, cost=0.1)
    layered = _stub_result("layered(claude-haiku-4-5/claude-sonnet-4-6)", n_urls=3, cost=0.05)

    with tempfile.TemporaryDirectory() as td:
        # path 指定なし → 自動命名を JST 化したか確認
        with patch.object(shw, "datetime", _FakeDT), \
             patch.object(shw, "LOG_DIR", Path(td)):
            written = shw.write_shadow_comparison(
                legacy, layered,
                caller="page1_master", articles=[{"url": "x"}],
            )
        expected_name = "stage2_shadow_2026-06-16.json"
        _check(
            "b17 ファイル名が JST 日付 (2026-06-16) で命名される",
            written.name == expected_name,
            f"got {written.name}",
        )
        body = json.loads(written.read_text(encoding="utf-8"))
        _check(
            "b18 JSON 内 date フィールドも JST 日付",
            body.get("date") == "2026-06-16",
            f"got {body.get('date')}",
        )


# ---------------------------------------------------------------------------
# (c) build_shadow_entry / shadow log structure
# ---------------------------------------------------------------------------

def test_shadow_entry_basic_structure():
    legacy = _stub_result("claude-sonnet-4-6", n_urls=5, cost=0.50)
    layered = _stub_result("layered(claude-haiku-4-5/claude-sonnet-4-6)", n_urls=5, cost=0.20)
    entry = shw.build_shadow_entry(
        legacy, layered, caller="page1_master", articles=[{"url": f"https://x/{i}"} for i in range(5)],
    )
    _check(
        "c1 build_shadow_entry: 必須キーすべて存在",
        all(k in entry for k in (
            "caller", "articles_count",
            "legacy_top_30", "layered_top_30",
            "overlap_count", "overlap_ratio",
            "legacy_cost_usd", "layered_cost_usd",
            "legacy_model", "layered_model",
            "layer_counts", "layered_evaluation_modes",
        )),
    )


def test_shadow_log_atomic_write_multi_callers():
    """複数 caller が同日に書き込み → 統合された 1 ファイル."""
    legacy = _stub_result("claude-sonnet-4-6", n_urls=3, cost=0.10)
    layered = _stub_result("layered(claude-haiku-4-5/claude-sonnet-4-6)", n_urls=3, cost=0.05)

    with tempfile.TemporaryDirectory() as td:
        log_path = Path(td) / "shadow.json"
        # page1_master 書き込み
        shw.write_shadow_comparison(
            legacy, layered,
            caller="page1_master", articles=[{"url": "x"}],
            path=log_path,
        )
        # page3 書き込み（既存 file を読んで追加）
        shw.write_shadow_comparison(
            legacy, layered,
            caller="page3", articles=[{"url": "y"}],
            path=log_path,
        )
        log = json.loads(log_path.read_text(encoding="utf-8"))
        leftover = [p.name for p in log_path.parent.iterdir() if p.name.startswith("shadow.json.")]

    _check(
        "c2 複数 caller 書き込み → 1 file 内に両方の entry",
        "page1_master" in log["callers"] and "page3" in log["callers"],
    )
    _check("c3 tmp ファイルは残らない（atomic rename）", leftover == [])


def test_shadow_log_overwrites_same_caller():
    """同一 caller が再度書き込んだ場合は entry を上書き."""
    legacy_v1 = _stub_result("claude-sonnet-4-6", n_urls=1, cost=0.10)
    legacy_v2 = _stub_result("claude-sonnet-4-6", n_urls=1, cost=0.20)
    layered = _stub_result("layered(claude-haiku-4-5/claude-sonnet-4-6)", n_urls=1, cost=0.05)

    with tempfile.TemporaryDirectory() as td:
        log_path = Path(td) / "shadow.json"
        shw.write_shadow_comparison(
            legacy_v1, layered, caller="page1_master",
            articles=[{"url": "x"}], path=log_path,
        )
        shw.write_shadow_comparison(
            legacy_v2, layered, caller="page1_master",
            articles=[{"url": "x"}], path=log_path,
        )
        log = json.loads(log_path.read_text(encoding="utf-8"))

    _check(
        "c4 同一 caller 再書き込み → 後の entry が勝つ",
        log["callers"]["page1_master"]["legacy_cost_usd"] == 0.20,
    )


def test_shadow_log_overlap_calculation():
    """legacy_top と layered_top の overlap_ratio が正しく計算される."""
    # legacy_top = {u0, u1, u2}、layered_top = {u1, u2, u3}
    # overlap = {u1, u2} = 2、min = 3 → ratio = 2/3 ≈ 0.6667
    legacy = Stage2Result(model="legacy")
    layered = Stage2Result(model="layered")
    for i, score in enumerate([100, 90, 80]):
        legacy.evaluations_by_url[f"https://x/{i}"] = {
            "final_score": float(score),
            "美意識1": 7, "美意識3": 8, "美意識5": 5,
            "美意識6": 4, "美意識8": 3,
        }
    for i, score in enumerate([95, 85, 75]):
        layered.evaluations_by_url[f"https://x/{i+1}"] = {
            "final_score": float(score),
            "美意識1": 7, "美意識3": 8, "美意識5": 5,
            "美意識6": 4, "美意識8": 3,
        }
    entry = shw.build_shadow_entry(
        legacy, layered, caller="test", articles=[{"url": f"https://x/{i}"} for i in range(4)],
    )
    _check(
        "c5 overlap_ratio: legacy {u0,u1,u2} vs layered {u1,u2,u3} = 2/3 = 0.6667",
        entry["overlap_count"] == 2
        and 0.66 <= entry["overlap_ratio"] <= 0.67,
        f"got count={entry['overlap_count']} ratio={entry['overlap_ratio']}",
    )


# ---------------------------------------------------------------------------
# (d) Scores log extended fields (Sub-Step 5a)
# ---------------------------------------------------------------------------

def test_to_log_entry_legacy_no_metadata_keys():
    """layer / evaluation_mode / caller を渡さない場合は scores log に出ない."""
    ev = {
        "scores": {
            "aesthetic_1_structure_detail": 7,
            "aesthetic_3_disciplinary_bridge": 8,
            "aesthetic_5_otherness": 5,
            "aesthetic_6_minority_value": 4,
            "aesthetic_8_behavioral_economics": 3,
        },
        "reasons": {k: f"r_{k[-1]}" for k in (
            "aesthetic_1_structure_detail",
            "aesthetic_3_disciplinary_bridge",
            "aesthetic_5_otherness",
            "aesthetic_6_minority_value",
            "aesthetic_8_behavioral_economics",
        )},
    }
    entry = s2_mod._to_log_entry(
        {"url": "x"}, ev, model="claude-sonnet-4-6",
        evaluated_at="2026-06-15T00:00:00Z",
    )
    _check(
        "d1 legacy 形式: layer / evaluation_mode / caller キーなし",
        "layer" not in entry and "evaluation_mode" not in entry
        and "caller" not in entry,
    )


def test_run_stage2_legacy_writes_caller_to_log_entry():
    """C93: run_stage2 legacy 経路でも caller / evaluation_mode が scores log に残る.

    C92 で発覚した C85 Sub-Step 5a の落ち（shadow scores ファイル内で
    layer / evaluation_mode / caller が全件 None）を修正したことを検証。
    """
    from scripts.selector.stage2 import run_stage2, BatchResult, Stage2Result
    from unittest.mock import patch

    fake_eval = {
        "scores": {
            "aesthetic_1_structure_detail": 6,
            "aesthetic_3_disciplinary_bridge": 5,
            "aesthetic_5_otherness": 4,
            "aesthetic_6_minority_value": 3,
            "aesthetic_8_behavioral_economics": 2,
        },
        "reasons": {k: "r" for k in (
            "aesthetic_1_structure_detail",
            "aesthetic_3_disciplinary_bridge",
            "aesthetic_5_otherness",
            "aesthetic_6_minority_value",
            "aesthetic_8_behavioral_economics",
        )},
    }
    fake_br = BatchResult(
        evaluations=[fake_eval], model="claude-sonnet-4-6",
        input_tokens=10, output_tokens=20,
        cache_creation_tokens=0, cache_read_tokens=0,
        cost_usd=0.001,
    )
    with patch("scripts.selector.stage2.evaluate_batch", return_value=fake_br), \
         patch("scripts.selector.stage2.llm_usage.check_caps",
               return_value=type("C", (), {"ok": True, "reason": ""})()), \
         patch("scripts.selector.stage2.write_scores_log"):
        result = run_stage2(
            [{"url": "https://x/1"}],
            caller="page3",  # 任意 caller を渡して伝播確認
        )
    entry = result.evaluations_by_url.get("https://x/1") or {}
    _check(
        "d3 C93 run_stage2 legacy: caller='page3' が記録される",
        entry.get("caller") == "page3",
        f"got caller={entry.get('caller')!r}",
    )
    _check(
        "d4 C93 run_stage2 legacy: evaluation_mode='legacy_sonnet' が記録される",
        entry.get("evaluation_mode") == "legacy_sonnet",
        f"got evaluation_mode={entry.get('evaluation_mode')!r}",
    )
    _check(
        "d5 C93 run_stage2 legacy: layer は記録しない（legacy 経路は layer 不明）",
        "layer" not in entry,
    )


def test_to_log_entry_layered_metadata():
    ev = {
        "scores": {
            "aesthetic_1_structure_detail": 7,
            "aesthetic_3_disciplinary_bridge": 8,
            "aesthetic_5_otherness": 0,
            "aesthetic_6_minority_value": 0,
            "aesthetic_8_behavioral_economics": 3,
        },
        "reasons": {k: "haiku_unscored" if "5" in k or "6" in k else "r" for k in (
            "aesthetic_1_structure_detail",
            "aesthetic_3_disciplinary_bridge",
            "aesthetic_5_otherness",
            "aesthetic_6_minority_value",
            "aesthetic_8_behavioral_economics",
        )},
    }
    entry = s2_mod._to_log_entry(
        {"url": "x"}, ev, model="claude-haiku-4-5",
        evaluated_at="2026-06-15T00:00:00Z",
        layer=2, evaluation_mode="haiku_prefilter_only", caller="page3",
    )
    _check(
        "d2 layered 形式: layer=2 / mode=haiku_prefilter_only / caller=page3",
        entry["layer"] == 2
        and entry["evaluation_mode"] == "haiku_prefilter_only"
        and entry["caller"] == "page3",
    )


def main() -> int:
    print("stage2_shadow + scores log unit tests (C85 Sub-Step 6-7)")
    print()
    print("(a) get_stage2_mode:")
    test_default_mode_is_legacy()
    test_mode_shadow()
    test_mode_layered()
    test_mode_invalid_falls_back()
    test_mode_case_insensitive()
    test_mode_shadow_page1_only_recognized()
    test_shadow_page1_only_callers_set()
    test_mode_layered_page1_recognized()
    test_layered_page1_callers_set()

    print()
    print("(b) run_stage2_with_mode dispatch:")
    test_dispatch_legacy_mode()
    test_dispatch_layered_mode()
    test_dispatch_shadow_mode_runs_both_and_returns_legacy()

    print()
    print("(b2) C86 shadow_page1_only:")
    test_dispatch_shadow_page1_only_for_master_caller()
    test_dispatch_shadow_page1_only_for_other_caller()
    test_dispatch_shadow_page1_only_for_page4_page5_page6()

    print()
    print("(b4) C93 layered_page1 (本番切替):")
    test_dispatch_layered_page1_for_master_caller()
    test_dispatch_layered_page1_for_other_callers()

    print()
    print("(b3) C88 JST date anchor:")
    test_jst_today_returns_date_object()
    test_jst_today_uses_tokyo_timezone()
    test_shadow_log_path_uses_jst_date()

    print()
    print("(c) build_shadow_entry / shadow log:")
    test_shadow_entry_basic_structure()
    test_shadow_log_atomic_write_multi_callers()
    test_shadow_log_overwrites_same_caller()
    test_shadow_log_overlap_calculation()

    print()
    print("(d) Scores log extended fields:")
    test_to_log_entry_legacy_no_metadata_keys()
    test_run_stage2_legacy_writes_caller_to_log_entry()
    test_to_log_entry_layered_metadata()

    print()
    print(f"=== {PASS} passed, {FAIL} failed ===")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
