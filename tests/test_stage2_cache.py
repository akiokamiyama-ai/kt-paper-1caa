"""Unit tests for C135 cross-day Stage 2 score cache.

Covers:
- ``_load_recent_scores`` file discovery + last-write-wins merge
- ``_is_cache_hit`` conservative Sonnet-only rule + model version check
- ``_apply_cache_hits`` split behavior + metadata attachment
- ``_get_cache_lookback_days`` env var override + parse errors
- ``run_stage2`` cache_lookback_days=0 revert behavior (legacy path)
- End-to-end: cached URLs skip LLM, uncached go through legacy/layered path

Run::

    python3 -m tests.test_stage2_cache
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import date
from pathlib import Path
from unittest.mock import patch

from scripts.selector import stage2
from scripts.selector.stage2 import (
    DEFAULT_CACHE_LOOKBACK_DAYS,
    DEFAULT_MODEL,
    ENV_CACHE_DAYS,
    _apply_cache_hits,
    _get_cache_lookback_days,
    _is_cache_hit,
    _load_recent_scores,
    _SONNET_FULL_MODES,
    LayerConfig,
    Stage2Result,
    run_stage2,
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
# Helpers
# ---------------------------------------------------------------------------

def _make_sonnet_entry(model: str = DEFAULT_MODEL, caller: str = "page3") -> dict:
    return {
        "美意識1": 6, "美意識3": 4, "美意識5": 5, "美意識6": 3, "美意識8": 2,
        "美意識2_machine": 5, "美意識4_penalty": 0, "final_score": None,
        "evaluation_reason": {"1": "r", "3": "r", "5": "r", "6": "r", "8": "r"},
        "evaluated_at": "2026-07-08T04:00:00Z",
        "model": model,
        "layer": 3,
        "evaluation_mode": "sonnet_full",
        "caller": caller,
    }


def _make_haiku_entry(caller: str = "page2") -> dict:
    return {
        "美意識1": 4, "美意識3": 3, "美意識5": 0, "美意識6": 0, "美意識8": 1,
        "美意識2_machine": 5, "美意識4_penalty": 0, "final_score": None,
        "evaluation_reason": {"1": "r", "3": "r", "5": "haiku_unscored",
                              "6": "haiku_unscored", "8": "r"},
        "evaluated_at": "2026-07-08T04:00:00Z",
        "model": "claude-haiku-4-5",
        "layer": 1,
        "evaluation_mode": "haiku_full",
        "caller": caller,
    }


def _make_legacy_entry() -> dict:
    """Pre-C85 legacy entry: model=sonnet, no evaluation_mode field."""
    return {
        "美意識1": 5, "美意識3": 5, "美意識5": 4, "美意識6": 3, "美意識8": 2,
        "美意識2_machine": 5, "美意識4_penalty": 0, "final_score": None,
        "evaluation_reason": {"1": "r", "3": "r", "5": "r", "6": "r", "8": "r"},
        "evaluated_at": "2026-06-30T04:00:00Z",
        "model": DEFAULT_MODEL,
        # No layer / evaluation_mode / caller (pre-C85 shape)
    }


# ---------------------------------------------------------------------------
# (a) _get_cache_lookback_days
# ---------------------------------------------------------------------------

def test_lookback_default():
    old = os.environ.pop(ENV_CACHE_DAYS, None)
    try:
        _check("a1 env 未設定 → DEFAULT_CACHE_LOOKBACK_DAYS",
               _get_cache_lookback_days() == DEFAULT_CACHE_LOOKBACK_DAYS)
    finally:
        if old is not None:
            os.environ[ENV_CACHE_DAYS] = old


def test_lookback_env_zero_disables():
    with patch.dict(os.environ, {ENV_CACHE_DAYS: "0"}):
        _check("a2 env=0 → 0（cache 無効化、revert 手段）",
               _get_cache_lookback_days() == 0)


def test_lookback_env_positive():
    with patch.dict(os.environ, {ENV_CACHE_DAYS: "3"}):
        _check("a3 env=3 → 3", _get_cache_lookback_days() == 3)


def test_lookback_env_negative_clamped_to_zero():
    with patch.dict(os.environ, {ENV_CACHE_DAYS: "-5"}):
        _check("a4 env=-5 → 0（負値は 0 にクランプ）",
               _get_cache_lookback_days() == 0)


def test_lookback_env_invalid_falls_back():
    with patch.dict(os.environ, {ENV_CACHE_DAYS: "abc"}):
        _check("a5 env=不正 → default に fallback",
               _get_cache_lookback_days() == DEFAULT_CACHE_LOOKBACK_DAYS)


# ---------------------------------------------------------------------------
# (b) _load_recent_scores
# ---------------------------------------------------------------------------

def test_load_disabled_returns_empty():
    with tempfile.TemporaryDirectory() as tmp:
        cache = _load_recent_scores(0, today=date(2026, 7, 9), log_dir=Path(tmp))
        _check("b1 lookback=0 → 空 dict（cache 無効化）", cache == {})


def test_load_missing_dir_returns_empty():
    cache = _load_recent_scores(7, today=date(2026, 7, 9),
                                log_dir=Path("/nonexistent/xxx"))
    _check("b2 log_dir 不在 → 空 dict（例外なし）", cache == {})


def test_load_reads_all_days_in_window():
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp)
        for offset in (1, 3, 7):
            d = date(2026, 7, 9) - _delta_days(offset)
            (p / f"scores_{d.isoformat()}.json").write_text(json.dumps({
                "date": d.isoformat(),
                "evaluations": {f"https://ex.com/{offset}": _make_sonnet_entry()},
            }))
        cache = _load_recent_scores(7, today=date(2026, 7, 9), log_dir=p)
        expected = {f"https://ex.com/{o}" for o in (1, 3, 7)}
        _check("b3 lookback=7 で 3 日分の URL が全て読み込まれる",
               set(cache.keys()) == expected,
               f"got {sorted(cache)}")


def test_load_excludes_today_by_default():
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp)
        for d, url in [
            (date(2026, 7, 9), "https://today.example.com/"),
            (date(2026, 7, 8), "https://yesterday.example.com/"),
        ]:
            (p / f"scores_{d.isoformat()}.json").write_text(json.dumps({
                "date": d.isoformat(),
                "evaluations": {url: _make_sonnet_entry()},
            }))
        cache = _load_recent_scores(7, today=date(2026, 7, 9), log_dir=p,
                                    exclude_today=True)
        _check("b4 exclude_today=True で今日の log は cache から除外",
               "https://today.example.com/" not in cache
               and "https://yesterday.example.com/" in cache)


def test_load_newer_overwrites_older():
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp)
        url = "https://ex.com/same-url"
        for d, model_v in [(date(2026, 7, 5), "old-model"),
                           (date(2026, 7, 8), "new-model")]:
            e = _make_sonnet_entry(model=model_v)
            (p / f"scores_{d.isoformat()}.json").write_text(json.dumps({
                "date": d.isoformat(), "evaluations": {url: e},
            }))
        cache = _load_recent_scores(7, today=date(2026, 7, 9), log_dir=p)
        _check("b5 同一 URL が複数日にある場合 newer で上書き",
               cache[url]["model"] == "new-model",
               f"got model={cache[url]['model']}")


def test_load_skips_malformed_json():
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp)
        (p / "scores_2026-07-08.json").write_text("{ not valid json")
        (p / "scores_2026-07-07.json").write_text(json.dumps({
            "date": "2026-07-07",
            "evaluations": {"https://ok.example.com/": _make_sonnet_entry()},
        }))
        cache = _load_recent_scores(7, today=date(2026, 7, 9), log_dir=p)
        _check("b6 malformed JSON は skip、他の日は読める",
               len(cache) == 1 and "https://ok.example.com/" in cache)


# ---------------------------------------------------------------------------
# (c) _is_cache_hit
# ---------------------------------------------------------------------------

def test_hit_sonnet_full():
    e = _make_sonnet_entry()
    _check("c1 sonnet_full → hit",
           _is_cache_hit(e, expected_sonnet_model=DEFAULT_MODEL) is True)


def test_hit_legacy_sonnet():
    e = _make_sonnet_entry()
    e["evaluation_mode"] = "legacy_sonnet"
    _check("c2 legacy_sonnet → hit",
           _is_cache_hit(e, expected_sonnet_model=DEFAULT_MODEL) is True)


def test_hit_pre_c85_none_mode():
    e = _make_legacy_entry()  # no evaluation_mode key at all
    _check("c3 pre-C85 legacy (evaluation_mode 欠落) → hit",
           _is_cache_hit(e, expected_sonnet_model=DEFAULT_MODEL) is True)


def test_miss_haiku_full():
    e = _make_haiku_entry()
    _check("c4 haiku_full → miss（美意識 5/6=0 の staleness 回避）",
           _is_cache_hit(e, expected_sonnet_model=DEFAULT_MODEL) is False)


def test_miss_haiku_prefilter_only():
    e = _make_haiku_entry()
    e["evaluation_mode"] = "haiku_prefilter_only"
    _check("c5 haiku_prefilter_only → miss",
           _is_cache_hit(e, expected_sonnet_model=DEFAULT_MODEL) is False)


def test_miss_model_version_mismatch():
    e = _make_sonnet_entry(model="claude-sonnet-4-5")  # older version
    _check("c6 モデル版数不一致 → miss（Sonnet 4.5 vs 4.6 の staleness）",
           _is_cache_hit(e, expected_sonnet_model=DEFAULT_MODEL) is False)


def test_miss_empty_model():
    e = _make_sonnet_entry()
    e["model"] = ""
    _check("c7 model 欠落 → miss（防御的）",
           _is_cache_hit(e, expected_sonnet_model=DEFAULT_MODEL) is False)


def test_miss_no_scores():
    e = _make_sonnet_entry()
    for k in ("美意識1", "美意識3", "美意識5", "美意識6", "美意識8"):
        e[k] = None
    _check("c8 スコア全 None → miss（データ壊れの防御）",
           _is_cache_hit(e, expected_sonnet_model=DEFAULT_MODEL) is False)


# ---------------------------------------------------------------------------
# (d) _apply_cache_hits
# ---------------------------------------------------------------------------

def test_apply_empty_cache_all_uncached():
    articles = [{"url": "https://a.example/"}, {"url": "https://b.example/"}]
    uncached, hits = _apply_cache_hits(
        articles, cache={}, expected_sonnet_model=DEFAULT_MODEL, caller="page3",
    )
    _check("d1 空 cache → 全 uncached",
           len(uncached) == 2 and hits == {})


def test_apply_hit_and_miss_split():
    articles = [
        {"url": "https://hit.example/"},
        {"url": "https://miss.example/"},  # not in cache
        {"url": "https://haiku.example/"},  # in cache but haiku
    ]
    cache = {
        "https://hit.example/": _make_sonnet_entry(),
        "https://haiku.example/": _make_haiku_entry(),
    }
    uncached, hits = _apply_cache_hits(
        articles, cache=cache, expected_sonnet_model=DEFAULT_MODEL,
        caller="page4",
    )
    _check("d2 sonnet hit / 不在 miss / haiku miss の分割",
           len(uncached) == 2 and "https://hit.example/" in hits
           and len(hits) == 1,
           f"uncached={[a['url'] for a in uncached]} hits={list(hits)}")


def test_apply_metadata_attached():
    cache = {"https://ex.example/": _make_sonnet_entry(caller="page2")}
    articles = [{"url": "https://ex.example/"}]
    _, hits = _apply_cache_hits(
        articles, cache=cache, expected_sonnet_model=DEFAULT_MODEL,
        caller="page3",
    )
    h = hits["https://ex.example/"]
    ok = (
        h["cache_hit"] is True
        and h["cache_original_caller"] == "page2"
        and h["cache_source_date"] == "2026-07-08"
        and h["caller"] == "page3"
        and h["final_score"] is None
        and h["美意識1"] == 6  # 元の値保持
    )
    _check("d3 cache hit エントリに正しいメタが付き caller が再割当される",
           ok, f"got h={h}")


def test_apply_url_missing_from_article():
    articles = [{"url": None}, {"url": ""}, {"no_url_key": True}]
    cache = {"https://ex.example/": _make_sonnet_entry()}
    uncached, hits = _apply_cache_hits(
        articles, cache=cache, expected_sonnet_model=DEFAULT_MODEL,
        caller="page3",
    )
    _check("d4 URL 欠落 article は全て uncached、hit は 0",
           len(uncached) == 3 and hits == {})


# ---------------------------------------------------------------------------
# (e) run_stage2 revert path — cache_lookback_days=0
# ---------------------------------------------------------------------------

def test_run_stage2_cache_disabled_lookback_zero():
    """cache_lookback_days=0 で cache lookup が起きず legacy 挙動になる."""
    with patch("scripts.selector.stage2._load_recent_scores") as mock_load, \
         patch("scripts.selector.stage2.write_scores_log"):
        mock_load.return_value = {}  # not called because lookback=0
        r = run_stage2([], cache_lookback_days=0)
        # _load_recent_scores IS called (even for empty articles) but with 0
        called_with_zero = (
            mock_load.call_args is not None
            and mock_load.call_args.args[0] == 0
        )
        _check("e1 cache_lookback_days=0 で lookback 引数=0 が渡る",
               called_with_zero and r.cache_hits_count == 0,
               f"call={mock_load.call_args}")


def test_run_stage2_env_zero_forces_legacy():
    """TRIBUNE_STAGE2_CACHE_DAYS=0 でも cache 経路が無効化される."""
    with patch.dict(os.environ, {ENV_CACHE_DAYS: "0"}), \
         patch("scripts.selector.stage2._load_recent_scores") as mock_load, \
         patch("scripts.selector.stage2.write_scores_log"):
        mock_load.return_value = {}
        r = run_stage2([])
        called_with_zero = (
            mock_load.call_args is not None
            and mock_load.call_args.args[0] == 0
        )
        _check("e2 env TRIBUNE_STAGE2_CACHE_DAYS=0 で lookback=0",
               called_with_zero and r.cache_hits_count == 0)


def test_run_stage2_writes_scores_log_once():
    """C135 refactor: write_scores_log は top-level で 1 回だけ呼ばれる."""
    with patch("scripts.selector.stage2._load_recent_scores") as mock_load, \
         patch("scripts.selector.stage2.write_scores_log") as mock_write:
        mock_load.return_value = {}
        # Legacy path with empty articles
        run_stage2([], cache_lookback_days=0)
        _check("e3 legacy path: write_scores_log は 1 回のみ呼ばれる",
               mock_write.call_count == 1,
               f"got {mock_write.call_count}")


def test_run_stage2_layered_writes_scores_log_once():
    """Layered 経路でも write_scores_log は top-level 1 回のみ."""
    with patch("scripts.selector.stage2._load_recent_scores") as mock_load, \
         patch("scripts.selector.stage2.write_scores_log") as mock_write:
        mock_load.return_value = {}
        run_stage2([], layer_config=LayerConfig(enabled=True),
                   caller="page1_master", cache_lookback_days=0)
        _check("e4 layered path: write_scores_log は 1 回のみ呼ばれる",
               mock_write.call_count == 1,
               f"got {mock_write.call_count}")


def test_run_stage2_cache_hits_end_to_end():
    """cache hit が LLM 呼び出しをスキップし、result に entry が入ることを検証."""
    with patch("scripts.selector.stage2._load_recent_scores") as mock_load, \
         patch("scripts.selector.stage2.evaluate_batch") as mock_eval, \
         patch("scripts.selector.stage2.write_scores_log"):
        # Cache has 2 articles, 1 hit + 1 miss
        cached_url = "https://hit.example/"
        uncached_url = "https://miss.example/"
        mock_load.return_value = {
            cached_url: _make_sonnet_entry(caller="page2"),
        }
        # LLM should only be called for the uncached one
        from scripts.selector.stage2 import BatchResult
        mock_eval.return_value = BatchResult(
            evaluations=[{
                "article_id": "art_001",
                "scores": {"aesthetic_1_structure_detail": 3,
                          "aesthetic_3_disciplinary_bridge": 3,
                          "aesthetic_5_otherness": 3,
                          "aesthetic_6_minority_value": 3,
                          "aesthetic_8_behavioral_economics": 3},
                "reasons": {"aesthetic_1_structure_detail": "",
                            "aesthetic_3_disciplinary_bridge": "",
                            "aesthetic_5_otherness": "",
                            "aesthetic_6_minority_value": "",
                            "aesthetic_8_behavioral_economics": ""},
            }],
            model=DEFAULT_MODEL,
        )

        articles = [
            {"url": cached_url, "title": "cached", "description": "d",
             "body": "b", "source_name": "s"},
            {"url": uncached_url, "title": "uncached", "description": "d",
             "body": "b", "source_name": "s"},
        ]
        r = run_stage2(articles, caller="page3", cache_lookback_days=7)
        ok = (
            r.cache_hits_count == 1
            and cached_url in r.evaluations_by_url
            and r.evaluations_by_url[cached_url].get("cache_hit") is True
            and r.evaluations_by_url[cached_url].get("caller") == "page3"
            and uncached_url in r.evaluations_by_url
            and mock_eval.call_count == 1  # only miss evaluated
        )
        _check("e5 hit=1 miss=1: LLM は 1 回のみ呼ばれ、両者が result に入る",
               ok,
               f"cache_hits={r.cache_hits_count} "
               f"llm_calls={mock_eval.call_count} "
               f"urls={list(r.evaluations_by_url)}")


# ---------------------------------------------------------------------------
# helper: local timedelta lookalike (avoid extra import)
# ---------------------------------------------------------------------------
from datetime import timedelta as _delta_days  # noqa: E402  used above


def main() -> int:
    print("Stage 2 cross-day cache unit tests (C135)")
    print()
    print("(a) _get_cache_lookback_days:")
    test_lookback_default()
    test_lookback_env_zero_disables()
    test_lookback_env_positive()
    test_lookback_env_negative_clamped_to_zero()
    test_lookback_env_invalid_falls_back()

    print()
    print("(b) _load_recent_scores:")
    test_load_disabled_returns_empty()
    test_load_missing_dir_returns_empty()
    test_load_reads_all_days_in_window()
    test_load_excludes_today_by_default()
    test_load_newer_overwrites_older()
    test_load_skips_malformed_json()

    print()
    print("(c) _is_cache_hit:")
    test_hit_sonnet_full()
    test_hit_legacy_sonnet()
    test_hit_pre_c85_none_mode()
    test_miss_haiku_full()
    test_miss_haiku_prefilter_only()
    test_miss_model_version_mismatch()
    test_miss_empty_model()
    test_miss_no_scores()

    print()
    print("(d) _apply_cache_hits:")
    test_apply_empty_cache_all_uncached()
    test_apply_hit_and_miss_split()
    test_apply_metadata_attached()
    test_apply_url_missing_from_article()

    print()
    print("(e) run_stage2 integration (revert + hit path):")
    test_run_stage2_cache_disabled_lookback_zero()
    test_run_stage2_env_zero_forces_legacy()
    test_run_stage2_writes_scores_log_once()
    test_run_stage2_layered_writes_scores_log_once()
    test_run_stage2_cache_hits_end_to_end()

    print()
    print(f"=== {PASS} passed, {FAIL} failed ===")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
