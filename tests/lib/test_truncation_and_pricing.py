"""max_tokens 切り詰めの検知と、価格テーブルの是正 (C205, 2026-09-21).

背景
----
C204 の副産物として 2 件見つかった。

**D: 切り詰めが検知されていなかった。**
``ClaudeResponse.stop_reason`` は前から埋まっていたが、**読む側が居なかった**
（editorial_writer が debug dict に入れるだけ）。90 日 (2026-06-24〜09-21) の
実測で 7943 呼び出し中 76 件 (0.96%) が ``output_tokens == max_tokens`` で
停止しており、40/90 日で起きていた。実害:

* stage2 では JSON が途中で切れ → parse 失敗 → nudge リトライが 67 回発火
  （``input_tokens`` が +85 ちょうど増えるので特定できる）。うち 4 回は
  2 回目も切れてバッチ全体が ``_fallback_eval``（全美意識スコア 3）に落ちた
* 2026-09-21 の 6 面料理は切り詰めで parse に失敗し、static fallback
  「鮭の塩焼き定食」が紙面に出た（cooking_history に 09-21 の entry が無い）

**A: 未知モデルのコストが 0 だった。**
``estimate_cost`` が未知モデルに 0.0 を返すため、モデル ID を差し替えて
``MODEL_PRICING`` への追加を忘れると全呼び出しが $0 で記録され、
``DAILY_COST_CAP_USD`` が**永久に発動しなくなる**。安全装置が黙って
無効化される形なので、最高単価で計上して WARN を出すように変えた。

Run::

    python3 -m tests.lib.test_truncation_and_pricing
"""

from __future__ import annotations

import io
import sys
from contextlib import redirect_stderr

from scripts.lib import llm, llm_usage

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
# (a) 価格テーブルが公式の値と一致する
# ---------------------------------------------------------------------------

# 出典: Anthropic 公式料金表、最終確認 2026-09-21。
OFFICIAL = {
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-sonnet-5":   (2.0, 10.0),
    "claude-opus-4-7":   (5.0, 25.0),
    "claude-haiku-4-5":  (1.0, 5.0),
}


def test_pricing_matches_official():
    for model, (inp, out) in OFFICIAL.items():
        r = llm_usage.MODEL_PRICING.get(model)
        _check(f"a1 {model} の単価が ${inp}/${out}",
               r is not None and r["input_per_mtok"] == inp
               and r["output_per_mtok"] == out,
               f"{r['input_per_mtok']}/{r['output_per_mtok']}" if r else "未登録")


def test_cache_rates_derived():
    """cache write = 1.25×input / cache read = 0.10×input の関係を保つ."""
    for model, r in llm_usage.MODEL_PRICING.items():
        inp = r["input_per_mtok"]
        _check(f"a2 {model} cache_write = 1.25×input",
               abs(r["cache_write_per_mtok"] - inp * 1.25) < 1e-9,
               str(r["cache_write_per_mtok"]))
        _check(f"a3 {model} cache_read = 0.10×input",
               abs(r["cache_read_per_mtok"] - inp * 0.10) < 1e-9,
               str(r["cache_read_per_mtok"]))


def test_haiku_regression():
    """C205 で是正した値に戻っていないこと（旧値 $0.80/$4.00）."""
    r = llm_usage.MODEL_PRICING["claude-haiku-4-5"]
    _check("a4 haiku が旧単価 $0.80/$4.00 に戻っていない",
           r["input_per_mtok"] != 0.80 and r["output_per_mtok"] != 4.0)


# ---------------------------------------------------------------------------
# (b) ★未知モデルで安全装置が死なないこと
# ---------------------------------------------------------------------------

def test_unknown_model_is_not_free():
    llm_usage._UNKNOWN_MODEL_WARNED.discard("claude-unknown-test")
    buf = io.StringIO()
    with redirect_stderr(buf):
        cost = llm_usage.estimate_cost("claude-unknown-test", 1_000_000, 1_000_000)
    _check("b1 ★未知モデルのコストが 0 ではない", cost > 0, f"${cost}")
    highest = max(llm_usage.MODEL_PRICING.values(),
                  key=lambda r: r["output_per_mtok"])
    expected = highest["input_per_mtok"] + highest["output_per_mtok"]
    _check("b2 最高単価で保守的に計上される",
           abs(cost - expected) < 1e-9, f"${cost} vs ${expected}")
    _check("b3 WARN が stderr に出る", "WARN" in buf.getvalue())


def test_unknown_model_warns_once():
    llm_usage._UNKNOWN_MODEL_WARNED.discard("claude-unknown-twice")
    b1, b2 = io.StringIO(), io.StringIO()
    with redirect_stderr(b1):
        llm_usage.estimate_cost("claude-unknown-twice", 100, 100)
    with redirect_stderr(b2):
        llm_usage.estimate_cost("claude-unknown-twice", 100, 100)
    _check("b4 WARN は 1 回だけ（ログを埋めない）",
           "WARN" in b1.getvalue() and "WARN" not in b2.getvalue())


def test_unknown_model_does_not_raise():
    """紙面生成を止めないこと."""
    try:
        llm_usage.estimate_cost("whatever", 1, 1)
        ok = True
    except Exception:
        ok = False
    _check("b5 未知モデルでも例外を投げない", ok)


def test_cap_would_fire_on_unknown_model():
    """未知モデルでも日次コストキャップが機能する（本来の目的）."""
    cost = llm_usage.estimate_cost("claude-unknown-cap", 0, 1_000_000)
    _check("b6 ★未知モデル 1M 出力で日次キャップ超えを検知できる",
           cost >= llm_usage.DAILY_COST_CAP_USD,
           f"${cost} vs cap ${llm_usage.DAILY_COST_CAP_USD}")


# ---------------------------------------------------------------------------
# (c) 切り詰めの検知
# ---------------------------------------------------------------------------

class _FakeUsage:
    def __init__(self, out):
        self.input_tokens = 100
        self.output_tokens = out
        self.cache_creation_input_tokens = 0
        self.cache_read_input_tokens = 0


class _FakeBlock:
    type = "text"
    text = "{}"


class _FakeResponse:
    def __init__(self, stop_reason, out):
        self.content = [_FakeBlock()]
        self.usage = _FakeUsage(out)
        self.stop_reason = stop_reason
        self.id = "msg_test"


def _call_with(stop_reason, out, max_tokens=4096):
    """call_claude を外部 I/O だけ差し替えて実行し、stderr を返す."""
    import types

    fake_anthropic = types.SimpleNamespace(
        Anthropic=lambda: types.SimpleNamespace(
            messages=types.SimpleNamespace(
                create=lambda **kw: _FakeResponse(stop_reason, out)
            )
        )
    )
    real_import = __builtins__["__import__"] if isinstance(__builtins__, dict) \
        else __builtins__.__import__

    def fake_import(name, *a, **kw):
        if name == "anthropic":
            return fake_anthropic
        return real_import(name, *a, **kw)

    orig_key = llm.get_api_key
    orig_record = llm_usage.record_call
    orig_caps = llm_usage.check_caps
    if isinstance(__builtins__, dict):
        __builtins__["__import__"] = fake_import
    else:
        __builtins__.__import__ = fake_import
    try:
        llm.get_api_key = lambda: "sk-ant-test"
        llm_usage.record_call = lambda *a, **kw: None
        llm_usage.check_caps = lambda *a, **kw: llm_usage.CapStatus(
            ok=True, reason="test", today_calls=0, today_cost_usd=0.0)
        buf = io.StringIO()
        with redirect_stderr(buf):
            resp = llm.call_claude(system="s", user="u", max_tokens=max_tokens,
                                   tag="test.tag")
        return resp, buf.getvalue()
    finally:
        if isinstance(__builtins__, dict):
            __builtins__["__import__"] = real_import
        else:
            __builtins__.__import__ = real_import
        llm.get_api_key = orig_key
        llm_usage.record_call = orig_record
        llm_usage.check_caps = orig_caps


def test_truncation_logs_warning():
    resp, err = _call_with("max_tokens", 4096)
    _check("c1 ★切り詰め時に TRUNCATED が stderr に出る", "TRUNCATED" in err,
           err.strip()[:70])
    _check("c2 タグが含まれる（どの呼び出しか分かる）", "test.tag" in err)
    _check("c3 stop_reason が返り値に入る", resp.stop_reason == "max_tokens")


def test_normal_stop_is_quiet():
    resp, err = _call_with("end_turn", 1200)
    _check("c4 正常終了では TRUNCATED を出さない", "TRUNCATED" not in err,
           err.strip()[:60])
    _check("c5 stop_reason=end_turn", resp.stop_reason == "end_turn")


# ---------------------------------------------------------------------------
# (d) 上限の引き上げが戻っていないこと
# ---------------------------------------------------------------------------

def test_caps_raised():
    from scripts.page6 import cooking_generator
    from scripts.selector import stage2

    _check("d1 stage2 の max_tokens が 8192 以上",
           stage2.DEFAULT_MAX_TOKENS >= 8192, str(stage2.DEFAULT_MAX_TOKENS))
    _check("d2 cooking の max_tokens が 3000 以上",
           cooking_generator.DEFAULT_MAX_TOKENS >= 3000,
           str(cooking_generator.DEFAULT_MAX_TOKENS))


def main() -> int:
    print("C205: 切り詰め検知 + 価格テーブル是正\n")
    print("(a) 価格テーブル:")
    test_pricing_matches_official()
    test_cache_rates_derived()
    test_haiku_regression()
    print()
    print("(b) ★未知モデルで安全装置が死なない:")
    test_unknown_model_is_not_free()
    test_unknown_model_warns_once()
    test_unknown_model_does_not_raise()
    test_cap_would_fire_on_unknown_model()
    print()
    print("(c) 切り詰めの検知:")
    test_truncation_logs_warning()
    test_normal_stop_is_quiet()
    print()
    print("(d) 上限:")
    test_caps_raised()
    print()
    print(f"=== {PASS} passed, {FAIL} failed ===")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
