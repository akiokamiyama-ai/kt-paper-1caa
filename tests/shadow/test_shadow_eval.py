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
from scripts.shadow.base import (
    AESTHETIC_KEYS, ShadowScore, UnknownProbabilityKeys, expected_score,
)
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

def test_expected_score_index_keys():
    """★Jev は probabilities を段階番号で返す（C212 の真因）."""
    _check("b1 段階 3 に全確率 → 9.5", expected_score({"3": 1.0}) == 9.5)
    _check("b2 段階 0 に全確率 → 1.0", expected_score({"0": 1.0}) == 1.0)
    _check("b3 段階 2 と 3 で半々 → 8.25",
           expected_score({"2": 0.5, "3": 0.5}) == 8.25)
    _check("b4 合計が 1 でなくても正規化",
           expected_score({"2": 0.4, "3": 0.4}) == 8.25)
    _check("b5 ★最頻値ではなく期待値（4 段階の粗さを潰さない）",
           0 < expected_score({"1": 0.6, "2": 0.4}) - 4.0 < 2.0,
           str(expected_score({"1": 0.6, "2": 0.4})))


def test_expected_score_real_probe_values():
    """★2026-10-06 の --probe 実測値を固定する（再現テスト）.

    確率は正常に返っていたのに score が全項目 0 になった事故の現物。
    """
    observed = {
        "美意識1": ({"0": 0.51, "1": 0.17, "2": 0.3, "3": 0.02}, 3.48),
        "美意識3": ({"0": 0.0, "1": 0.01, "2": 0.57, "3": 0.42}, 8.02),
        "美意識5": ({"0": 0.09, "1": 0.29, "2": 0.56, "3": 0.06}, 5.74),
        "美意識6": ({"0": 0.31, "1": 0.26, "2": 0.22, "3": 0.21}, 4.885),
        "美意識8": ({"0": 0.99, "1": 0.01, "2": 0.0, "3": 0.0}, 1.03),
    }
    for jp, (probs, want) in observed.items():
        got = expected_score(probs)
        _check(f"b6 {jp} の実測値 → {want}", abs(got - want) < 1e-9, str(got))
        _check(f"b7 {jp} は 0 にならない", got > 0)


def test_unknown_keys_raise_not_zero():
    """★黙って 0 を返さない。2 週間分を無駄にしないための要件."""
    for bad, label in [({"low": 0.5, "high": 0.5}, "バンド名でも番号でもない"),
                       ({}, "空"),
                       ({"9": 1.0}, "範囲外の段階番号")]:
        try:
            v = expected_score(bad)
            raised = False
        except UnknownProbabilityKeys:
            raised = True; v = None
        _check(f"b8 ★{label} → 0 ではなく例外", raised, f"返り値 {v}")


def test_band_name_keys_still_work():
    """保険：将来 API がバンド名で返しても落ちない."""
    _check("b9 バンド名キーも受ける", expected_score({"6-8": 1.0}) == 7.0)
    _check("b10 en dash も正規化", expected_score({"6–8": 1.0}) == 7.0)


# ---------------------------------------------------------------------------
# (c) HTTP を差し替えた Jev
# ---------------------------------------------------------------------------

def _fake_response(conf=0.8):
    return {
        "model": "jev-latest",
        "usage": {"input_tokens": 1200, "output_tokens": 0},
        "answers": {
            eng: {"type": "score", "score": 7,
                  "legend": {}, "probabilities": {"2": 0.7, "3": 0.3},
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
    _check("c3 段階番号から期待値になる（2:0.7 + 3:0.3 → 7.75）",
           abs(r.scores["aesthetic_1_structure_detail"] - 7.75) < 1e-6,
           str(r.scores["aesthetic_1_structure_detail"]))
    _check("c4 confidence が別に記録される",
           r.confidence["aesthetic_1_structure_detail"] == 0.8)
    _check("c5 コストは入力のみ（出力無料）",
           abs(r.cost_usd - 1200 / 1e6 * 0.042) < 1e-12, f"${r.cost_usd}")
    # C213: build_state は本番の _format_article_block をそのまま使うので、
    #       文字列を返す。切り方の検証は (g) に移した。
    _check("c6 state は本番と同じ文字列形式",
           isinstance(s.build_state(_ART), str)
           and s.build_state(_ART).startswith("[art_shadow]"),
           s.build_state(_ART)[:24])


def test_jev_zero_score_regression():
    """★確率が返っているのに score が 0 になる事故（C212）の回帰."""
    s = _FakeJev()
    [r] = s.score_articles([_ART])
    zeros = [k for k, v in r.scores.items() if v == 0]
    _check("c11 ★確率があるのに 0 の項目が無い", not zeros, str(zeros))
    _check("c12 Jev の生 score も記録する（写像の検算用）",
           len(r.raw_scores) == 5, str(r.raw_scores))


def test_jev_unmappable_probs_become_error():
    """★対応づけできないキーは 0 ではなく error 扱い."""
    class _Bad(_FakeJev):
        def _post(self, payload):
            self.calls += 1
            return {"usage": {}, "answers": {
                eng: {"type": "score", "probabilities": {"low": 1.0}}
                for eng, _jp in AESTHETIC_KEYS}}
    [r] = _Bad().score_articles([_ART])
    _check("c13 ★scores は空（0 を並べない）", r.scores == {}, str(r.scores))
    _check("c14 error に理由が入る",
           "UnknownProbabilityKeys" in (r.error or ""), (r.error or "")[:50])


def test_jev_missing_answer_is_error():
    class _Short(_FakeJev):
        def _post(self, payload):
            self.calls += 1
            return {"usage": {}, "answers": {"aesthetic_1_structure_detail":
                    {"type": "score", "probabilities": {"3": 1.0}}}}
    [r] = _Short().score_articles([_ART])
    _check("c15 項目が足りなければ error", bool(r.error), (r.error or "")[:50])


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
    """store が壊れていても例外を外に出さない.

    C213: scorer を fake に差し替える。以前は TYPESAFE_API_KEY=dummy で
    **実際に api.typesafe.ai へ 401 を投げていた**（テストが毎回ネットワークを
    叩くのは筋が悪い）。
    """
    import scripts.shadow.runner as runner_mod

    os.environ["TRIBUNE_SHADOW_SCORER"] = "jev"
    orig_build = runner_mod._build_scorer
    orig_path = store.log_path
    try:
        runner_mod._build_scorer = lambda name: _FakeJev()
        store.log_path = lambda *a, **k: Path("/proc/does-not-exist/x.json")
        try:
            maybe_run_shadow([_ART], _EVALS, caller="page3")
            raised = False
        except Exception:  # noqa: BLE001
            raised = True
    finally:
        runner_mod._build_scorer = orig_build
        store.log_path = orig_path
        del os.environ["TRIBUNE_SHADOW_SCORER"]
    _check("d4 ★書き込み不能でも投げない", not raised)


def test_runner_records_baseline_meta():
    """★layer / 未採点項目を記録する（compare が層別に出せるように）."""
    import scripts.shadow.runner as runner_mod

    evals = {"https://x.test/a": {
        **{jp: 6 for _e, jp in AESTHETIC_KEYS},
        "layer": 1, "evaluation_mode": "haiku_full",
        "evaluation_reason": {"1": "r", "3": "r", "5": "haiku_unscored",
                              "6": "haiku_unscored", "8": "r"},
    }}
    os.environ["TRIBUNE_SHADOW_SCORER"] = "jev"
    orig_build = runner_mod._build_scorer
    with tempfile.TemporaryDirectory() as td:
        pth = Path(td) / "s.json"
        orig_path = store.log_path
        try:
            runner_mod._build_scorer = lambda name: _FakeJev()
            store.log_path = lambda *a, **k: pth
            maybe_run_shadow([_ART], evals, caller="page6")
            rows = store.load(pth)["entries"]
        finally:
            runner_mod._build_scorer = orig_build
            store.log_path = orig_path
            del os.environ["TRIBUNE_SHADOW_SCORER"]
    _check("d9 記録される", len(rows) == 1, str(len(rows)))
    m = rows[0].get("baseline_meta") or {} if rows else {}
    _check("d10 ★未採点項目が印される",
           m.get("unscored") == ["美意識5", "美意識6"], str(m.get("unscored")))
    _check("d11 layer / mode が残る",
           m.get("layer") == 1 and m.get("evaluation_mode") == "haiku_full", str(m))


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
    r = compare.summarize(entries)["jev / unknown"]
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
    r = compare.summarize(entries)["jev / unknown"]
    _check("f11 失敗件数が出る", r["n_error"] == 1)
    _check("f12 失敗理由が集計される", r["errors"] and "401" in r["errors"][0][0])




# ---------------------------------------------------------------------------
# (g) C213: 初日データで見つかった 4 件
# ---------------------------------------------------------------------------

def test_upsert_key_includes_caller():
    """★caller をまたいだ同一 URL が上書きされない（10/6 初日に 21 件消えた）."""
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "s.json"
        for caller in ("page3", "page3_serendipity"):
            e = ShadowScore(url="same", scorer="jev", scores={"a": 1.0}).to_entry()
            e["caller"] = caller
            store.record([e], path=p)
        rows = store.load(p)["entries"]
    _check("g1 ★同一 URL でも caller が違えば両方残る", len(rows) == 2, str(len(rows)))
    _check("g2 caller が保たれる",
           sorted(r["caller"] for r in rows) == ["page3", "page3_serendipity"])


def test_same_caller_still_upserts():
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "s.json"
        for v in (1.0, 9.0):
            e = ShadowScore(url="u", scorer="jev", scores={"a": v}).to_entry()
            e["caller"] = "page3"
            store.record([e], path=p)
        rows = store.load(p)["entries"]
    _check("g3 同一 caller なら従来どおり upsert", len(rows) == 1, str(len(rows)))
    _check("g4 後の値で上書き", rows[0]["scores"]["a"] == 9.0)


def test_state_matches_production_exactly():
    """★Jev の state が本番 Sonnet に渡すのと同一文字列であること."""
    from scripts.selector.stage2 import _format_article_block

    for label, art in [
        ("description 長い", {"title": "T", "source_name": "S",
                              "description": "d" * 300, "body": "B" * 5000}),
        ("description 短い", {"title": "T", "source_name": "S",
                              "description": "d" * 20, "body": "本文。" * 500}),
        ("body なし", {"title": "T", "source_name": "S", "description": "d" * 10}),
    ]:
        want = _format_article_block("art_shadow", art)
        got = JevScorer.build_state(art)
        _check(f"g5 {label}: 本番と完全一致", got == want,
               f"{len(got)} 字 vs {len(want)} 字")


def test_long_description_excludes_body():
    """★英語論考（description 長い）で body を渡さない（本番と同じ）."""
    art = {"title": "The FY2017 Defense Budget", "source_name": "Foreign Affairs",
           "description": "d" * 300, "body": "B" * 5000}
    st = JevScorer.build_state(art)
    _check("g6 ★body を含めない（Sonnet も見ていない）", "body:" not in st)
    _check("g7 2,000 字の生本文が入らない", len(st) < 500, f"{len(st)} 字")


def _entry(mode, unscored, base, shadow, caller="page3"):
    return {"url": f"u{base}{shadow}{mode}", "scorer": "jev", "caller": caller,
            "scores": {eng: float(shadow) for eng, _jp in AESTHETIC_KEYS},
            "baseline": {jp: base for _eng, jp in AESTHETIC_KEYS},
            "baseline_meta": {"layer": 1 if mode.startswith("haiku") else 3,
                              "evaluation_mode": mode, "unscored": unscored},
            "cost_usd": 0.00006, "elapsed_ms": 300, "error": None}


def test_haiku_unscored_is_excluded():
    """★haiku_unscored の項目は相関計算から外す."""
    rows = [_entry("haiku_prefilter_only", ["美意識5", "美意識6"], i, i)
            for i in range(1, 6)]
    r = compare.summarize(rows)["jev / haiku"]
    _check("g8 ★美意識5 は全件除外されて n=0",
           r["per_aesthetic"]["美意識5"]["n"] == 0
           and r["per_aesthetic"]["美意識5"]["excluded_unscored"] == 5,
           str(r["per_aesthetic"]["美意識5"]))
    _check("g9 採点済みの項目は計算される",
           r["per_aesthetic"]["美意識1"]["n"] == 5)
    _check("g10 未採点を含む記事は final_score から外す",
           r["final_score"].get("n") == 0, str(r["final_score"]))


def test_layer_split():
    """★baseline を layer（haiku / sonnet）別に分けて出す."""
    rows = ([_entry("haiku_full", ["美意識5", "美意識6"], i, i) for i in range(1, 5)]
            + [_entry("sonnet_full", [], i, i) for i in range(1, 5)])
    res = compare.summarize(rows)
    _check("g11 ★haiku と sonnet_full が別グループになる",
           sorted(res) == ["jev / haiku", "jev / sonnet_full"], str(sorted(res)))
    _check("g12 sonnet_full では 5 項目すべて計算される",
           all(res["jev / sonnet_full"]["per_aesthetic"][jp]["n"] == 4
               for _e, jp in AESTHETIC_KEYS))


def test_spearman_is_primary():
    """★順位相関が主指標。値域が揃わなくても順位が合えば 1.0."""
    # 本番 0..4、Jev は 1.0 未満を返せないので 1.0..5.0。順位は同じ。
    rows = []
    for i in range(5):
        e = _entry("sonnet_full", [], i, i + 1.0)
        rows.append(e)
    r = compare.summarize(rows)["jev / sonnet_full"]
    d = r["per_aesthetic"]["美意識1"]
    _check("g13 ★床が違っても Spearman=1.0", d["spearman"] == 1.0, str(d["spearman"]))
    _check("g14 Pearson も併記される", d["pearson"] is not None)


# ---------------------------------------------------------------------------
# (h) C214: Jev-B（全文）の並走
# ---------------------------------------------------------------------------

def test_multi_scorer_spec():
    from scripts.shadow.runner import _build_scorers
    _check("h1 カンマ区切りで 2 つ並走",
           [s.name for s in _build_scorers("jev,jev_fulltext")]
           == ["jev", "jev_fulltext"])
    _check("h2 ★typo が混ざっても残りは走る",
           [s.name for s in _build_scorers("jev,nope,jev_fulltext")]
           == ["jev", "jev_fulltext"])
    _check("h3 空なら 0 件", _build_scorers("") == [])


def test_fulltext_state_differs():
    from scripts.shadow.jev import JevFullTextScorer as B

    art = {"title": "T", "source_name": "S",
           "description": "d" * 300, "body": "B" * 50000}
    a = JevScorer.build_state(art)
    b = B.build_state(art)
    _check("h4 ★A は本番規則で body を落とす", "body:" not in a)
    _check("h5 ★B は description が長くても body を入れる", "body:" in b)
    _check("h6 B は上限で切る", len(b) <= B.FULLTEXT_LIMIT + 500, f"{len(b)} 字")


def test_fulltext_skips_duplicate_body():
    """★JFA / PPC の driver は body_paragraphs=[description] を入れてくる."""
    from scripts.shadow.jev import JevFullTextScorer as B

    art = {"title": "T", "source_name": "S", "description": "同じ本文",
           "body": "同じ本文"}
    st = B.build_state(art)
    _check("h7 ★body==description なら重複させない", "body:" not in st, st[:60])


def test_fulltext_equals_a_when_no_body():
    """★body が無ければ A と B は実質同じ（131 ソース中 127 がこれ）."""
    from scripts.shadow.jev import JevFullTextScorer as B

    art = {"title": "T", "source_name": "S", "description": "d" * 20, "body": ""}
    a = JevScorer.build_state(art)
    b = B.build_state(art)
    _check("h8 ★本文が無ければ中身は同じ",
           a.split("\n")[1:] == b.split("\n")[1:],
           f"A {len(a)} 字 / B {len(b)} 字")


def _pair(url, caller, scorer, vals, unscored=()):
    return {"url": url, "caller": caller, "scorer": scorer,
            "scores": {eng: float(v) for (eng, _jp), v in zip(AESTHETIC_KEYS, vals)},
            "baseline": {jp: 5 for _e, jp in AESTHETIC_KEYS},
            "baseline_meta": {"layer": 3, "evaluation_mode": "sonnet_full",
                              "unscored": list(unscored)},
            "state_chars": 400 if scorer == "jev" else 4000,
            "error": None, "cost_usd": 0.00006, "elapsed_ms": 200}


def test_cross_compare():
    rows = []
    for i in range(5):
        rows.append(_pair(f"u{i}", "page3", "jev", [i + 1] * 5))
        rows.append(_pair(f"u{i}", "page3", "jev_fulltext", [i + 1] * 5))
    x = compare.cross_compare(rows)
    _check("h9 ★A/B が同一記事で組になる", x["n_pairs"] == 5, str(x["n_pairs"]))
    _check("h10 一致していれば Spearman=1.0",
           x["per_aesthetic"]["美意識1"]["spearman"] == 1.0)
    _check("h11 入力規模の差が出る",
           x["state_chars"]["b_larger"] == 5, str(x.get("state_chars")))


def test_cross_compare_needs_both():
    rows = [_pair("u1", "page3", "jev", [5] * 5)]
    _check("h12 片方だけなら組にならない",
           compare.cross_compare(rows)["n_pairs"] == 0)


def test_cross_compare_respects_caller():
    """同じ URL でも caller が違えば別の組（C213 の upsert と整合）."""
    rows = [_pair("u1", "page3", "jev", [5] * 5),
            _pair("u1", "page6", "jev_fulltext", [5] * 5)]
    _check("h13 caller が違う組は組まない",
           compare.cross_compare(rows)["n_pairs"] == 0)


def test_divergent_ranks_by_abs_diff():
    rows = []
    for i, v in enumerate([5, 1, 9]):     # baseline 5 固定に対し差 0 / -4 / +4
        rows.append(_pair(f"u{i}", "page3", "jev_fulltext", [v] * 5))
    out = compare.divergent(rows, top=3)
    _check("h14 ★差の絶対値で並ぶ",
           abs(out[0]["diff"]) >= abs(out[-1]["diff"]),
           str([r["diff"] for r in out]))
    _check("h15 差 0 は最後", out[-1]["diff"] == 0.0, str(out[-1]["diff"]))


def test_divergent_excludes_unscored():
    """★未採点を含む記事は除く（差が項目欠落に由来してしまう）."""
    rows = [_pair("u1", "page3", "jev_fulltext", [1] * 5,
                  unscored=["美意識5", "美意識6"])]
    _check("h16 ★未採点を含む記事は乖離一覧に出さない",
           compare.divergent(rows, top=5) == [])



# ---------------------------------------------------------------------------
# (i) C215: 2 週間分を artifact から読む
# ---------------------------------------------------------------------------

def test_load_range_from_log_dir():
    """★shadow ログは .gitignore 対象で artifact にしか残らない.

    10/20 に `compare --days 14` を回すには artifact を展開した先を
    直接読めないといけない。
    """
    import json as _json
    from datetime import date as _date, timedelta as _td

    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        today = _date.today()
        for i, n in [(0, 2), (3, 1), (30, 5)]:      # 30 日前は範囲外
            day = (today - _td(days=i)).isoformat()
            (d / f"shadow_eval_{day}.json").write_text(_json.dumps({
                "date": day,
                "entries": [{"url": f"u{i}{k}", "scorer": "jev", "caller": "page3",
                             "scores": {}, "baseline": {}} for k in range(n)],
            }), encoding="utf-8")
        rows = store.load_range(14, log_dir=d)
    _check("i1 ★範囲内の日付だけ読む（2+1=3 件、30 日前は除く）",
           len(rows) == 3, str(len(rows)))
    _check("i2 date が補われる", all(r.get("date") for r in rows))


def test_load_range_ignores_out_of_range():
    import json as _json
    from datetime import date as _date, timedelta as _td

    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        old = (_date.today() - _td(days=100)).isoformat()
        (d / f"shadow_eval_{old}.json").write_text(_json.dumps({
            "date": old, "entries": [{"url": "u", "scorer": "jev"}]}),
            encoding="utf-8")
        rows = store.load_range(14, log_dir=d)
    _check("i3 古いファイルは拾わない", rows == [], str(len(rows)))


def test_fetch_script_uses_repo_flag():
    """★C200 の教訓: gh run download は --repo が無いと repo 外で即終了する."""
    sh = (Path(__file__).resolve().parents[2]
          / "scripts" / "tools" / "fetch_shadow_logs.sh").read_text(encoding="utf-8")
    _check("i4 ★gh run download に --repo がある",
           'gh run download "$id" --repo' in sh)
    _check("i5 gh run list にも --repo がある", "--repo \"$REPO\"" in sh)
    _check("i6 C200 の経緯がコメントに残っている", "C200" in sh)



def main() -> int:
    print("C211/C213: shadow 評価の枠組み（実 API は叩かない）\n")
    print("(a) rubric は原典から:")
    test_criteria_from_production_prompt(); test_questions_shape()
    print()
    print("(b) バンド確率 → 0–10:")
    test_expected_score_index_keys(); test_expected_score_real_probe_values()
    test_unknown_keys_raise_not_zero(); test_band_name_keys_still_work()
    print()
    print("(c) Jev（HTTP 差し替え）:")
    test_jev_happy_path(); test_jev_zero_score_regression()
    test_jev_unmappable_probs_become_error(); test_jev_missing_answer_is_error()
    test_jev_errors_do_not_raise()
    test_jev_unavailable_without_key()
    print()
    print("(d) ★既定で無効 / 紙面を落とさない:")
    test_disabled_by_default(); test_unknown_scorer_is_skipped()
    test_missing_key_is_skipped(); test_runner_never_raises()
    test_runner_records_baseline_meta()
    test_stage2_hook_is_wrapped()
    print()
    print("(e) store:")
    test_store_upsert(); test_store_broken_file()
    print()
    print("(f) 相関:")
    test_correlation_math(); test_summarize_uses_production_formula()
    test_summarize_counts_errors()
    print()
    print("(g) C213 初日データの修正:")
    test_upsert_key_includes_caller(); test_same_caller_still_upserts()
    test_state_matches_production_exactly(); test_long_description_excludes_body()
    test_haiku_unscored_is_excluded(); test_layer_split()
    test_spearman_is_primary()
    print()
    print("(h) C214 Jev-B（全文）の並走:")
    test_multi_scorer_spec(); test_fulltext_state_differs()
    test_fulltext_skips_duplicate_body(); test_fulltext_equals_a_when_no_body()
    test_cross_compare(); test_cross_compare_needs_both()
    test_cross_compare_respects_caller()
    test_divergent_ranks_by_abs_diff(); test_divergent_excludes_unscored()
    print()
    print("(i) C215 artifact から 2 週間分を読む:")
    test_load_range_from_log_dir(); test_load_range_ignores_out_of_range()
    test_fetch_script_uses_repo_flag()
    print()
    print(f"=== {PASS} passed, {FAIL} failed ===")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
