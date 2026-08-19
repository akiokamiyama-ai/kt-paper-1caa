"""quote_excerpt の和訳化と字数上限 (C176, 2026-08-19).

背景
----
C174 / C175 で真因が確定した。``quote_excerpt`` の「原文ママ、訳出は不要」指示
により主軸記事の英文引用がそのまま JSON 文字列値に入り、内部の ``"`` を
エスケープし損ねて構文が壊れていた（8/19 W13 Day 4、char 2200 の
``"Friendliness"``）。

さらに実測で、プロンプトの「300-500 字」は事実上機能していなかった:

    fallback を除く 76 本  min=164 / p50=631 / p90=1058 / max=1405
    500 字超  53 本 (70%)

長い引用ほど内部に引用符を含む確率が上がる。8/19 の破損は 1,074 字の引用で
起きた。

対処は 2 本立て:
  1. 引用を**和訳ベース**にして ASCII ダブルクォートの混入源を断つ
  2. 字数上限を**実効化**する（超過は句点優先で切り詰め、必ず記録）

C175 の救済はフェイルセーフとして残す（和訳化しても破損確率はゼロにならない）。

Tests:
  a) プロンプトが和訳・「」・字数厳守を指示している
  b) 上限内はそのまま
  c) 超過は切り詰められる
  d) 切り詰めたら必ず記録（C156 の教訓）
  e) 句点優先で切れる
  f) C175 の救済が残っている（フェイルセーフ）

Run::

    python3 -m tests.page1_v3.test_quote_excerpt_policy
"""

from __future__ import annotations

import io
import json
import sys
import tempfile
from contextlib import redirect_stderr
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from scripts.page1_v3 import essay_generator as eg
from scripts.page1_v3.monthly_pivotal import WeekContext
from scripts.page1_v3.prompts import ESSAY_SYSTEM_PROMPT

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


@dataclass
class _FakeResp:
    text: str
    cost_usd: float = 0.05


def _wc() -> WeekContext:
    return WeekContext(
        week_label="W13", theme="自己搾取の時代",
        period=(date(2026, 8, 16), date(2026, 8, 22)),
        article={
            "title": "Five Ways to Read Byung-Chul Han",
            "source": "The Philosopher", "author": "A", "published": "2025",
            "url": "https://x/", "summary": "S", "points": ["P1"],
            "key_quote": "Q", "key_quote_ja": "ハンはこれを「肯定的暴力」と呼ぶ。",
        },
        day_label="水", angle_key="thinker", angle_label_jp="思想家",
    )


def _payload(quote: str) -> str:
    return json.dumps({
        "daily_question": "問い" * 5, "essay_title": "T",
        "body": "本文" * 100, "annotation_label": "L",
        "annotation_body": "A", "quote_excerpt": quote,
    })


# ---------------------------------------------------------------------------
# (a) プロンプト
# ---------------------------------------------------------------------------

def test_prompt_requires_japanese():
    p = ESSAY_SYSTEM_PROMPT
    _check("a1 quote_excerpt 専用ルールの節がある", "quote_excerpt のルール" in p)
    _check("a2 日本語訳を指示している", "日本語訳で書く" in p)
    _check("a3 原文ママ指示が消えている", "原文ママ" not in p)
    _check("a4 和訳＋原語括弧の例がある", "Freundlichkeit" in p)
    _check("a5 「」を使うよう指示", "「」を使う" in p)
    _check("a6 ASCII ダブルクォート回避を明示",
           "ダブルクォート" in p and "使わない" in p)
    _check("a7 300-500 字の厳守を指示", "300-500 字を厳守" in p)
    _check("a8 出力スキーマ側も和訳指示に更新されている",
           "日本語訳で 300-500 字" in p)


# ---------------------------------------------------------------------------
# (b)(c)(e) 字数上限
# ---------------------------------------------------------------------------

def test_within_limit_untouched():
    q = "短い引用。" * 20  # 100 字
    _check("b1 上限内は無改変", eg._enforce_quote_limit(q) == q, f"{len(q)} 字")


def test_exactly_at_limit():
    q = "あ" * eg.QUOTE_EXCERPT_MAX_CHARS
    _check("b2 ちょうど上限は無改変", eg._enforce_quote_limit(q) == q)


def test_over_limit_truncated():
    q = "これは長い引用文である。" * 100
    with redirect_stderr(io.StringIO()):
        out = eg._enforce_quote_limit(q)
    _check("c1 超過分は切り詰められる",
           len(out) <= eg.QUOTE_EXCERPT_MAX_CHARS, f"{len(q)} → {len(out)} 字")


def test_truncates_at_sentence_end():
    q = "これは長い引用文である。" * 100
    with redirect_stderr(io.StringIO()):
        out = eg._enforce_quote_limit(q)
    _check("e1 句点で切れる（途中で切れた文にしない）",
           out.endswith("。"), repr(out[-12:]))


def test_ellipsis_when_no_sentence_break():
    q = "句点のない引用" * 100
    with redirect_stderr(io.StringIO()):
        out = eg._enforce_quote_limit(q)
    _check("e2 句点が無ければ … を付ける", out.endswith("…"), repr(out[-6:]))


def test_limit_matches_spec():
    _check("c2 上限がプロンプトの仕様（500 字）と一致",
           eg.QUOTE_EXCERPT_MAX_CHARS == 500,
           str(eg.QUOTE_EXCERPT_MAX_CHARS))


# ---------------------------------------------------------------------------
# (d) 記録
# ---------------------------------------------------------------------------

def test_truncation_is_logged():
    q = "これは長い引用文である。" * 100
    buf = io.StringIO()
    with redirect_stderr(buf):
        eg._enforce_quote_limit(q)
    out = buf.getvalue()
    _check("d1 切り詰めを WARN で記録", "WARN" in out and "切り詰め" in out,
           out.strip()[:80])
    _check("d2 元の字数が記録される", str(len(q)) in out)


def test_no_log_within_limit():
    buf = io.StringIO()
    with redirect_stderr(buf):
        eg._enforce_quote_limit("短い引用。")
    _check("d3 上限内なら記録しない", buf.getvalue() == "")


def test_limit_applied_end_to_end():
    long_quote = "これは長い引用文である。" * 100

    def fake(*, system, user):
        return _FakeResp(text=_payload(long_quote))

    buf = io.StringIO()
    with redirect_stderr(buf):
        r = eg.generate_essay(_wc(), date(2026, 8, 20), llm_caller=fake)
    _check("d4 generate_essay 経由でも上限が効く",
           len(r.quote_excerpt) <= eg.QUOTE_EXCERPT_MAX_CHARS,
           f"{len(r.quote_excerpt)} 字")
    _check("d5 論考本体は影響を受けない", r.is_fallback is False)


# ---------------------------------------------------------------------------
# (f) C175 の救済はフェイルセーフとして残す
# ---------------------------------------------------------------------------

def test_c175_salvage_still_works():
    broken = (
        '{"daily_question": "問い", "essay_title": "T", "body": "本文", '
        '"annotation_label": "L", "annotation_body": "A", '
        '"quote_excerpt": "和訳しても "こう" 壊れる余地は残る"}'
    )
    r = eg._parse_essay_json(broken)
    _check("f1 構文破損の救済が残っている（和訳化は確率を下げるだけ）",
           r.data is not None and r.rescued == ("quote_excerpt",),
           str(r.reason))


def test_rescued_quote_also_limited():
    """救済時の代替（key_quote_ja）にも上限が効くこと。"""
    payload = json.loads(_payload("x"))
    del payload["quote_excerpt"]

    def fake(*, system, user):
        return _FakeResp(text=json.dumps(payload))

    with tempfile.TemporaryDirectory() as td, redirect_stderr(io.StringIO()):
        r = eg.generate_essay(_wc(), date(2026, 8, 20), llm_caller=fake,
                              fallback_raw_dir=Path(td))
    _check("f2 救済経路でも上限内",
           len(r.quote_excerpt) <= eg.QUOTE_EXCERPT_MAX_CHARS,
           f"{len(r.quote_excerpt)} 字")


def main() -> int:
    print("C176: quote_excerpt の和訳化と字数上限\n")
    print("(a) プロンプト:")
    test_prompt_requires_japanese()
    print()
    print("(b) 上限内は無改変:")
    test_within_limit_untouched()
    test_exactly_at_limit()
    print()
    print("(c) 超過は切り詰め:")
    test_over_limit_truncated()
    test_limit_matches_spec()
    print()
    print("(d) 切り詰めの記録:")
    test_truncation_is_logged()
    test_no_log_within_limit()
    test_limit_applied_end_to_end()
    print()
    print("(e) 句点優先:")
    test_truncates_at_sentence_end()
    test_ellipsis_when_no_sentence_break()
    print()
    print("(f) C175 救済の維持:")
    test_c175_salvage_still_works()
    test_rescued_quote_also_limited()
    print()
    print(f"=== {PASS} passed, {FAIL} failed ===")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
