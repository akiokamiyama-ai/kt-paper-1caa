"""shadow 評価の枠組み (C211, 2026-10-05).

実 API（api.typesafe.ai）は **一切叩かない**。HTTP を差し替えて全経路を固める。
2026-10-05 時点で Jev の API キーが未取得で、日本語入力が通るかも未確認なので、
「キーが取れたら動く」ことを offline で保証しておく。

このテストが固めること:

* **既定で完全に無効**（``TRIBUNE_SHADOW_SCORER`` 未設定なら何もしない）
* **shadow は紙面を落とさない**（HTTP 失敗 / 不正な応答 / store 書込失敗でも
  例外が外に出ない）
* 本番プロンプトの美意識バンドが 5 項目 × 4 段階で取れる
* バンド確率 → 0–10 の期待値への写像
* 相関の計算（Pearson / Spearman、同順位の扱い）
* store の upsert

Run::

    python3 -m tests.shadow.test_shadow_eval
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

from scripts.shadow import compare, store
from scripts.shadow.base import AESTHETIC_KEYS, ShadowScore, expected_score
from scripts.shadow.jev import JevScorer, build_criteria
from scripts.shadow.runner import maybe_run_shadow

PASS = 0
FAIL = 0


def _check(label: str, cond: bool, detail: str = "") -> bool:
    global PASS, FAIL
    line = f"  {'✓' if cond else '✗'} {label}"
    if detail:
        line += f"  ({detail})"
    print(line)
    if cond:
        PASS += 1
    else:
        FAIL += 1
    return cond


# ---------------------------------------------------------------------------
# (a) rubric は原典から取る
# ---------------------------------------------------------------------------

def test_criteria_from_production_prompt():
    c = build_criteria()
    _check("a1 美意識 5 項目すべてのバンドが取れる",
           sorted(c) == ["美意識1", "美意識3", "美意識5", "美意識6", "美意識8"],
           str(sorted(c)))
    for jp, spec in c.items():
        _check(f"a2 {jp} は 4 段階", len(spec["bands"]) == 4, str(sorted(spec["bands"])))
        _check(f"a3 {jp} に評価軸の説明がある", len(spec["instructions"]) > 20,
               f"{len(spec['instructions'])} 字")


def test_questions_shape():
    q = JevScorer(api_key="dummy").build_questions()
    _check("a4 質問は 5 本", len(q) == 5, str(len(q)))
    one = q["aesthetic_1_structure_detail"]
    _check("a5 type は score", one["type"] == "score")
    _check("a6 criteria は低い順（0-2 が先頭）",
           one["criteria"][0].startswith("0-2"), one["criteria"][0][:20])
    _check("a7 criteria は 2〜10 段階に収まる", 2 <= len(one["criteria"]) <= 10,
           str(len(one["criteria"])))


# ---------------------------------------------------------------------------
# (b) バンド確率 → 0–10
# ---------------------------------------------------------------------------

def test_expected_score():
    _check("b1 9-10 に全確率 → 9.5",
           expected_score({"9-10": 1.0}) == 9.5)
    _check("b2 0-2 に全確率 → 1.0",
           expected_score({"0-2": 1.0}) == 1.0)
    _check("b3 6-8 と 9-10 で半々 → 8.25",
           expected_score({"6-8": 0.5, "9-10": 0.5}) == 8.25)
    _check("b4 合計が 1 でなくても正規化する",
           expected_score({"6-8": 0.4, "9-10": 0.4}) == 8.25)
    _check("b5 空なら 0", expected_score({}) == 0.0)
    _check("b6 未知のバンドは無視",
           expected_score({"9-10": 1.0, "99": 5.0}) == 9.5)
    _check("b7 ★最頻値ではなく期待値（4 段階の粗さを潰さない）",
           0 < expected_score({"3-5": 0.6, "6-8": 0.4}) - 4.0 < 2.0,
           str(expected_score({"3-5": 0.6, "6-8": 0.4})))


# ---------------------------------------------------------------------------
# (c) HTTP を差し替えた Jev
# ---------------------------------------------------------------------------

def _fake_response(conf=0.8):
    return {
        "model": "jev-latest",
        "usage": {"input_tokens": 1200, "output_tokens": 0},
        "answers": {
            eng: {"type": "score", "score": 7,
                  "legend": {}, "probabilities": {"6–8": 0.7, "9–10": 0.3},
                  "confidence": conf}
            for eng, _jp in AESTHETIC_KEYS
        },
    }


class _FakeJev(JevScorer):
    def __init__(self, behavior="ok", **kw):
        super().__init__(api_key="dummy", **kw)
        self.behavior = behavior
        self.calls = 0

    def _post(self, payload):
        self.calls += 1
        if self.behavior == "ok":
            return _fake_response()
        if self.behavior == "raise":
            raise RuntimeError("boom")
        if self.behavior == "garbage":
            return {"answers": {"wrong_key": {"type": "noul", "noul": 0.5}}}
        raise AssertionError(self.behavior)


_ART = {"url": "https://x.test/a", "title": "t", "source_name": "s",
        "description": "d" * 50, "body": "b" * 5000}


def test_jev_happy_path():
    s = _FakeJev()
    [r] = s.score_articles([_ART])
    _check("c1 エラー無し", r.error is None, str(r.error))
    _check("c2 5 項目のスコアが入る", len(r.scores) == 5, str(r.scores))
    _check("c3 en dash のバンド名も正規化される（6–8 → 6-8）",
           abs(r.scores["aesthetic_1_structure_detail"] - 7.75) < 1e-6,
           str(r.scores["aesthetic_1_structure_detail"]))
    _check("c4 confidence が別に記録される",
           r.confidence["aesthetic_1_structure_detail"] == 0.8)
    _check("c5 コストは入力のみ（出力無料）",
           abs(r.cost_usd - 1200 / 1e6 * 0.042) < 1e-12, f"${r.cost_usd}")
    _check("c6 本文は BODY_LIMIT で切る",
           len(s.build_state(_ART)["body"]) == 2000)


def test_jev_errors_do_not_raise():
    for beh, label in [("raise", "例外"), ("garbage", "不正な応答")]:
        s = _FakeJev(beh)
        try:
            [r] = s.score_articles([_ART])
            raised = False
        except Exception:  # noqa: BLE001
            raised = True
        _check(f"c7 ★{label}でも score_articles は投げない", not raised)
        if beh == "raise":
            _check("c8 理由が error に入る", bool(r.error), str(r.error)[:40])


def test_jev_unavailable_without_key():
    ok, why = JevScorer(api_key=None).available()
    _check("c9 キー未設定なら available=False", ok is False)
    _check("c10 理由に環境変数名が出る", "TYPESAFE_API_KEY" in why, why[:50])


# ---------------------------------------------------------------------------
# (d) ★既定で無効 / 紙面を落とさない
# ---------------------------------------------------------------------------

_EVALS = {"https://x.test/a": {jp: 6 for _e, jp in AESTHETIC_KEYS}}


def test_disabled_by_default():
    saved = os.environ.pop("TRIBUNE_SHADOW_SCORER", None)
    try:
        n = maybe_run_shadow([_ART], _EVALS, caller="page3")
    finally:
        if saved is not None:
            os.environ["TRIBUNE_SHADOW_SCORER"] = saved
    _check("d1 ★環境変数が無ければ何もしない", n == 0, str(n))


def test_unknown_scorer_is_skipped():
    os.environ["TRIBUNE_SHADOW_SCORER"] = "does-not-exist"
    try:
        n = maybe_run_shadow([_ART], _EVALS, caller="page3")
    finally:
        del os.environ["TRIBUNE_SHADOW_SCORER"]
    _check("d2 未知の scorer なら skip", n == 0, str(n))


def test_missing_key_is_skipped():
    os.environ["TRIBUNE_SHADOW_SCORER"] = "jev"
    saved = os.environ.pop("TYPESAFE_API_KEY", None)
    try:
        n = maybe_run_shadow([_ART], _EVALS, caller="page3")
    finally:
        del os.environ["TRIBUNE_SHADOW_SCORER"]
        if saved is not None:
            os.environ["TYPESAFE_API_KEY"] = saved
    _check("d3 ★キーが無ければ skip（本番に影響しない）", n == 0, str(n))


def test_runner_never_raises():
    """store が壊れていても例外を外に出さない."""
    os.environ["TRIBUNE_SHADOW_SCORER"] = "jev"
    os.environ["TYPESAFE_API_KEY"] = "dummy"
    orig = store.log_path
    try:
        store.log_path = lambda *a, **k: Path("/proc/does-not-exist/x.json")
        try:
            n = maybe_run_shadow([_ART], _EVALS, caller="page3")
            raised = False
        except Exception:  # noqa: BLE001
            raised = True
    finally:
        store.log_path = orig
        del os.environ["TRIBUNE_SHADOW_SCORER"]
        del os.environ["TYPESAFE_API_KEY"]
    _check("d4 ★書き込み不能でも投げない", not raised)


def test_stage2_hook_is_wrapped():
    src = (Path(__file__).resolve().parents[2]
           / "scripts" / "selector" / "stage2.py").read_text(encoding="utf-8")
    # import 行ではなく **呼び出し本体** を見る（コメント中の語に釣られない）。
    i = src.find("maybe_run_shadow(articles")
    _check("d5 stage2 に配線されている", i > 0)
    # 呼び出しから遡って、コメント・空行・import を飛ばした最初の構文行が try。
    lines = src[:i].splitlines()
    prev = ""
    for l in reversed(lines[:-1]):
        t = l.strip()
        if not t or t.startswith("#") or t.startswith("from ") or t.startswith("import "):
            continue
        prev = t
        break
    _check("d6 ★呼び出しが try の中にある", prev == "try:", f"直前の構文行: {prev!r}")
    # 呼び出しの後に except がある
    after = src[i:i + 500]
    _check("d7 except で受けている", "except Exception" in after)
    # write_scores_log の **呼び出し** より後ろにある
    w = src.find("\n    write_scores_log(result)")
    _check("d8 write_scores_log の後に置かれている", 0 < w < i, f"w={w} i={i}")


# ---------------------------------------------------------------------------
# (e) store
# ---------------------------------------------------------------------------

def test_store_upsert():
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "s.json"
        e1 = ShadowScore(url="u1", scorer="jev", scores={"a": 1.0}).to_entry()
        store.record([e1], path=p)
        e2 = dict(e1); e2["scores"] = {"a": 9.0}
        store.record([e2], path=p)
        rows = store.load(p)["entries"]
    _check("e1 同一 (url, scorer) は upsert", len(rows) == 1, str(len(rows)))
    _check("e2 後の値で上書き", rows and rows[0]["scores"]["a"] == 9.0)


def test_store_broken_file():
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "s.json"
        p.write_text("{ broken", encoding="utf-8")
        n = store.record([ShadowScore(url="u", scorer="jev", scores={}).to_entry()],
                         path=p)
    _check("e3 壊れたログでも書き直せる", n == 1, str(n))


# ---------------------------------------------------------------------------
# (f) 相関
# ---------------------------------------------------------------------------

def test_correlation_math():
    _check("f1 完全一致で Pearson=1.0",
           compare.pearson([1, 2, 3, 4], [1, 2, 3, 4]) == 1.0)
    _check("f2 完全逆順で -1.0",
           compare.pearson([1, 2, 3, 4], [4, 3, 2, 1]) == -1.0)
    _check("f3 定数列は None（0 除算を避ける）",
           compare.pearson([1, 1, 1, 1], [1, 2, 3, 4]) is None)
    _check("f4 件数不足は None", compare.pearson([1, 2], [1, 2]) is None)
    _check("f5 Spearman は単調変換に不変",
           compare.spearman([1, 2, 3, 4], [1, 4, 9, 16]) == 1.0)
    _check("f6 同順位は平均順位",
           compare.spearman([1, 1, 2, 3], [1, 1, 2, 3]) == 1.0)


def test_summarize_uses_production_formula():
    entries = []
    for i in range(5):
        entries.append({
            "url": f"u{i}", "scorer": "jev",
            "scores": {eng: float(i + 1) for eng, _jp in AESTHETIC_KEYS},
            "confidence": {eng: 0.7 for eng, _jp in AESTHETIC_KEYS},
            "baseline": {jp: i + 1 for _eng, jp in AESTHETIC_KEYS},
            "cost_usd": 0.00005, "elapsed_ms": 300, "error": None,
        })
    r = compare.summarize(entries)["jev"]
    _check("f7 成功 5 件", r["n_ok"] == 5, str(r["n_ok"]))
    _check("f8 一致していれば項目別 Pearson=1.0",
           r["per_aesthetic"]["美意識1"]["pearson"] == 1.0)
    _check("f9 final_score も本番式で計算される",
           r["final_score"].get("spearman") == 1.0, str(r["final_score"]))
    _check("f10 1 件あたりコストとレイテンシが出る",
           r["cost_per_article"] == 5e-05 and r["latency_ms_median"] == 300)


def test_summarize_counts_errors():
    entries = [{"url": "u", "scorer": "jev", "scores": {}, "baseline": {},
                "error": "HTTP 401: nope"}]
    r = compare.summarize(entries)["jev"]
    _check("f11 失敗件数が出る", r["n_error"] == 1)
    _check("f12 失敗理由が集計される", r["errors"] and "401" in r["errors"][0][0])


def main() -> int:
    print("C211: shadow 評価の枠組み（実 API は叩かない）\n")
    print("(a) rubric は原典から:")
    test_criteria_from_production_prompt(); test_questions_shape()
    print()
    print("(b) バンド確率 → 0–10:")
    test_expected_score()
    print()
    print("(c) Jev（HTTP 差し替え）:")
    test_jev_happy_path(); test_jev_errors_do_not_raise()
    test_jev_unavailable_without_key()
    print()
    print("(d) ★既定で無効 / 紙面を落とさない:")
    test_disabled_by_default(); test_unknown_scorer_is_skipped()
    test_missing_key_is_skipped(); test_runner_never_raises()
    test_stage2_hook_is_wrapped()
    print()
    print("(e) store:")
    test_store_upsert(); test_store_broken_file()
    print()
    print("(f) 相関:")
    test_correlation_math(); test_summarize_uses_production_formula()
    test_summarize_counts_errors()
    print()
    print(f"=== {PASS} passed, {FAIL} failed ===")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
