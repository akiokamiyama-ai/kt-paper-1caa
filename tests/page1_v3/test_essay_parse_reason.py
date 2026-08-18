"""page1_v3 essay の parse 失敗理由と部分救済 (C172, 2026-08-19).

背景
----
2026-08-19（W13 Day 4, 水曜 thinker）に Page I の論考が休載した。応答は完結
しており（output 2252 / 1969 tokens、上限 4096 に未達）**切り捨てではない**。
76 本中初の fallback。

原因追求は 2 箇所で止まった:

  1. C24 (2026-05-24) が入れた診断ファイル ``logs/page1_v3_fallback_raw_*.txt``
     が artifact / git add / .gitignore の 3 経路とも未収録で、3 ヶ月間
     runner 上に書かれては捨てられていた。初めて必要になった日に無かった
  2. ``_parse_essay_json`` が構文破損・dict 非該当・必須キー欠落をすべて
     ``None`` で返し、呼び出し側が一律 ``"JSON parse failed"`` とログしていた

有力仮説（未確定）: ``quote_excerpt`` の「原文ママ」指示 + 主軸記事
（Byung-Chul Han、full_text_excerpt 27,201 字）に含まれる ASCII ダブル
クォート 88 個。水曜 thinker は術語（引用符で囲まれた箇所）を取りに行く。

Tests:
  a) 各失敗理由が正しく返る
  b) quote_excerpt だけ壊れた場合の 5 キー救済
  c) body 等が欠けた場合は従来どおり fallback
  d) 救済したことが stderr に記録される（C156 の教訓）
  e) リトライ時に 1 回目の理由も残る
  f) 回帰: 診断ファイルが artifact path に入っている

Run::

    python3 -m tests.page1_v3.test_essay_parse_reason
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
            "source": "The Philosopher",
            "author": "Wyllie & Knepper",
            "published": "2025",
            "url": "https://x/",
            "summary": "S",
            "points": ["P1"],
            "key_quote": 'Han calls this "positive violence".',
            "key_quote_ja": "ハンはこれを「肯定的暴力」と呼ぶ。",
        },
        day_label="水", angle_key="thinker", angle_label_jp="思想家",
    )


def _payload(**over) -> dict:
    base = {
        "daily_question": "問い" * 5,
        "essay_title": "タイトル",
        "body": "本文" * 100,
        "annotation_label": "中心思想家と主著",
        "annotation_body": "解説",
        "quote_excerpt": "原文引用",
    }
    base.update(over)
    return base


# ---------------------------------------------------------------------------
# (a) 失敗理由
# ---------------------------------------------------------------------------

def test_reason_empty_response():
    r = eg._parse_essay_json("")
    _check("a1 空応答 → empty_response",
           r.data is None and r.reason == "empty_response", str(r.reason))


def test_reason_no_json_object():
    r = eg._parse_essay_json("ここには JSON がありません")
    _check("a2 { が無い → no_json_object",
           r.data is None and r.reason == "no_json_object", str(r.reason))


def test_reason_decode_error():
    # 8/19 の仮説の再現: 原文ママ引用のダブルクォートが未エスケープ
    broken = (
        '{"daily_question": "問い", "essay_title": "T", "body": "本文", '
        '"annotation_label": "L", "annotation_body": "A", '
        '"quote_excerpt": "Han calls this "positive violence" here."}'
    )
    r = eg._parse_essay_json(broken)
    ok = r.data is None and (r.reason or "").startswith("decode_error")
    _check("a3 未エスケープの \" → decode_error", ok, str(r.reason))
    _check("a3b decode_error に文字位置が入る（どこで転んだかの手掛かり）",
           "char" in (r.reason or ""), str(r.reason))


def test_reason_not_dict():
    r = eg._parse_essay_json("[1, 2, 3]")
    # 先頭が { でないので no_json_object になる。dict 非該当は { 始まりで検出。
    r2 = eg._parse_essay_json('{"a": 1}')
    _check("a4 配列 → 失敗理由が付く", r.data is None and r.reason is not None,
           str(r.reason))
    _check("a4b キー欠落の dict → missing_key",
           r2.data is None and "missing_key" in (r2.reason or ""), str(r2.reason))


def test_reason_missing_and_empty_key():
    p = _payload()
    del p["body"]
    r = eg._parse_essay_json(json.dumps(p))
    _check("a5 body 欠落 → missing_key:body",
           r.data is None and r.reason == "missing_key:body", str(r.reason))

    r2 = eg._parse_essay_json(json.dumps(_payload(body="   ")))
    _check("a6 body 空文字 → empty_value:body",
           r2.data is None and r2.reason == "empty_value:body", str(r2.reason))

    r3 = eg._parse_essay_json(json.dumps(_payload(body=123)))
    ok = r3.data is None and "wrong_type" in (r3.reason or "") and "body" in (r3.reason or "")
    _check("a7 body が str でない → wrong_type", ok, str(r3.reason))


def test_reason_lists_all_blocking_keys():
    p = _payload()
    del p["body"]
    del p["essay_title"]
    r = eg._parse_essay_json(json.dumps(p))
    ok = r.data is None and "body" in (r.reason or "") and "essay_title" in (r.reason or "")
    _check("a8 複数キーが壊れたら全部理由に出る", ok, str(r.reason))


# ---------------------------------------------------------------------------
# (b) quote_excerpt の部分救済
# ---------------------------------------------------------------------------

def test_rescue_missing_quote():
    p = _payload()
    del p["quote_excerpt"]
    r = eg._parse_essay_json(json.dumps(p))
    ok = r.data is not None and r.rescued == ("quote_excerpt",)
    _check("b1 quote_excerpt 欠落 → 5 キーで救済", ok,
           f"rescued={r.rescued}, reason={r.reason}")
    _check("b2 救済時も理由は残る",
           "missing_key:quote_excerpt" in (r.reason or ""), str(r.reason))


def test_rescue_empty_quote():
    r = eg._parse_essay_json(json.dumps(_payload(quote_excerpt="  ")))
    _check("b3 quote_excerpt 空文字 → 救済",
           r.data is not None and r.rescued == ("quote_excerpt",), str(r.reason))


def test_rescue_fills_key_quote_ja():
    def fake(*, system, user):
        p = _payload()
        del p["quote_excerpt"]
        return _FakeResp(text=json.dumps(p))

    with tempfile.TemporaryDirectory() as td, redirect_stderr(io.StringIO()):
        res = eg.generate_essay(_wc(), date(2026, 8, 19), llm_caller=fake,
                                fallback_raw_dir=Path(td))
    _check("b4 救済時は紙面が成立する（is_fallback=False）",
           res.is_fallback is False, f"title={res.essay_title}")
    _check("b5 quote_excerpt に key_quote_ja が入る",
           res.quote_excerpt == "ハンはこれを「肯定的暴力」と呼ぶ。",
           res.quote_excerpt)
    _check("b6 論考本文は採用される", len(res.body) > 100, f"{len(res.body)} 字")


def test_rescue_only_for_quote_excerpt():
    _check("b7 救済対象は quote_excerpt のみ",
           eg.RESCUABLE_KEYS == frozenset({"quote_excerpt"}),
           str(sorted(eg.RESCUABLE_KEYS)))


# ---------------------------------------------------------------------------
# (c) 救済しないケース
# ---------------------------------------------------------------------------

def test_body_missing_still_fallback():
    def fake(*, system, user):
        p = _payload()
        del p["body"]
        return _FakeResp(text=json.dumps(p))

    with tempfile.TemporaryDirectory() as td, redirect_stderr(io.StringIO()):
        res = eg.generate_essay(_wc(), date(2026, 8, 19), llm_caller=fake,
                                fallback_raw_dir=Path(td))
    _check("c1 body 欠落は従来どおり fallback（本文が無ければ紙面が成立しない）",
           res.is_fallback is True, res.essay_title)


def test_quote_plus_body_broken_is_fallback():
    p = _payload()
    del p["body"]
    del p["quote_excerpt"]
    r = eg._parse_essay_json(json.dumps(p))
    _check("c2 救済可能キー + 致命キーが両方壊れたら fallback",
           r.data is None and "body" in (r.reason or ""), str(r.reason))


# ---------------------------------------------------------------------------
# (d) 救済の記録（C156 の教訓）
# ---------------------------------------------------------------------------

def test_rescue_is_logged():
    def fake(*, system, user):
        p = _payload()
        del p["quote_excerpt"]
        return _FakeResp(text=json.dumps(p))

    buf = io.StringIO()
    with tempfile.TemporaryDirectory() as td, redirect_stderr(buf):
        eg.generate_essay(_wc(), date(2026, 8, 19), llm_caller=fake,
                          fallback_raw_dir=Path(td))
    out = buf.getvalue()
    _check("d1 救済したことが stderr に出る", "WARN" in out and "救済" in out,
           out.strip()[:90])
    _check("d2 救済したキー名が出る", "quote_excerpt" in out)


def test_no_log_when_clean():
    def fake(*, system, user):
        return _FakeResp(text=json.dumps(_payload()))

    buf = io.StringIO()
    with redirect_stderr(buf):
        eg.generate_essay(_wc(), date(2026, 8, 19), llm_caller=fake)
    _check("d3 正常時は救済ログを出さない", "救済" not in buf.getvalue())


# ---------------------------------------------------------------------------
# (e) リトライ時に 1 回目の理由が残る
# ---------------------------------------------------------------------------

def test_attempt1_reason_logged_on_retry():
    calls = {"n": 0}

    def fake(*, system, user):
        calls["n"] += 1
        if calls["n"] == 1:
            return _FakeResp(text=json.dumps(_payload(body="")))
        return _FakeResp(text=json.dumps(_payload()))

    buf = io.StringIO()
    with tempfile.TemporaryDirectory() as td, redirect_stderr(buf):
        res = eg.generate_essay(_wc(), date(2026, 8, 19), llm_caller=fake,
                                fallback_raw_dir=Path(td))
    out = buf.getvalue()
    _check("e1 2 回目で成功する", res.is_fallback is False)
    _check("e2 1 回目の理由が stderr に出る",
           "empty_value:body" in out, out.strip()[:110])


def test_both_attempts_reasons_in_dump():
    def fake(*, system, user):
        return _FakeResp(text=json.dumps(_payload(body="")))

    with tempfile.TemporaryDirectory() as td:
        buf = io.StringIO()
        with redirect_stderr(buf):
            res = eg.generate_essay(_wc(), date(2026, 8, 19), llm_caller=fake,
                                    fallback_raw_dir=Path(td))
        dumps = list(Path(td).glob("page1_v3_fallback_raw_*.txt"))
        _check("e3 両方失敗 → fallback", res.is_fallback is True)
        _check("e4 raw ダンプが書かれる", len(dumps) == 1,
               str([p.name for p in dumps]))
        if dumps:
            text = dumps[0].read_text(encoding="utf-8")
            _check("e5 ダンプに両 attempt の理由が入る",
                   text.count("empty_value:body") == 2, text[:80])
        _check("e6 fallback の reason に両方の理由が入る",
               "empty_value:body" in buf.getvalue())


# ---------------------------------------------------------------------------
# (f) 回帰: 診断ファイルが実際に artifact に入っている
# ---------------------------------------------------------------------------

def test_workflow_uploads_fallback_raw():
    """C24 の抜けの回帰防止。ここが落ちたら次の休載は追えなくなる。"""
    wf = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "daily.yml"
    if not wf.exists():
        _check("f1 daily.yml が見つかる", False, str(wf))
        return
    text = wf.read_text(encoding="utf-8")
    _check("f1 artifact path に page1_v3_fallback_raw_*.txt がある",
           "logs/page1_v3_fallback_raw_*.txt" in text)
    # literal block scalar 内なので、行頭 # のコメントは glob に渡ってしまう
    in_path = False
    bad: list[str] = []
    for line in text.splitlines():
        if line.strip().startswith("path: |"):
            in_path = True
            continue
        if in_path:
            if line.strip() and not line.startswith(" " * 12):
                in_path = False
                continue
            if line.strip().startswith("#"):
                bad.append(line.strip())
    _check("f2 path ブロック内にコメント行が無い（# は glob に渡る）",
           not bad, str(bad[:2]))


def test_filename_convention_matches():
    """コードが書くファイル名と workflow の glob が一致すること。"""
    with tempfile.TemporaryDirectory() as td:
        p = eg._save_fallback_raw(date(2026, 8, 19), "raw", Path(td))
        _check("f3 命名規約が glob に一致",
               p is not None and p.name == "page1_v3_fallback_raw_2026-08-19.txt",
               p.name if p else "None")


def main() -> int:
    print("C172: essay parse 失敗理由と部分救済\n")
    print("(a) 失敗理由の区別:")
    test_reason_empty_response()
    test_reason_no_json_object()
    test_reason_decode_error()
    test_reason_not_dict()
    test_reason_missing_and_empty_key()
    test_reason_lists_all_blocking_keys()
    print()
    print("(b) quote_excerpt の部分救済:")
    test_rescue_missing_quote()
    test_rescue_empty_quote()
    test_rescue_fills_key_quote_ja()
    test_rescue_only_for_quote_excerpt()
    print()
    print("(c) 救済しないケース:")
    test_body_missing_still_fallback()
    test_quote_plus_body_broken_is_fallback()
    print()
    print("(d) 救済の記録:")
    test_rescue_is_logged()
    test_no_log_when_clean()
    print()
    print("(e) リトライ時の理由保持:")
    test_attempt1_reason_logged_on_retry()
    test_both_attempts_reasons_in_dump()
    print()
    print("(f) 回帰: 診断ファイルの実収録:")
    test_workflow_uploads_fallback_raw()
    test_filename_convention_matches()
    print()
    print(f"=== {PASS} passed, {FAIL} failed ===")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
