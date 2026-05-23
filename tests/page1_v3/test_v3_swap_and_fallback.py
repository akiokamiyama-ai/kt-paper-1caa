"""Tests for regen_front_page_v3 の swap + fallback ロジック (Phase 3, 2026-05-23).

実 LLM / v2 main は呼ばない（mock + ファイル操作のみ）。

Run::

    python3 -m tests.page1_v3.test_v3_swap_and_fallback
"""

from __future__ import annotations

import sys
import tempfile
from datetime import date
from pathlib import Path
from unittest import mock

from scripts import regen_front_page_v3 as v3
from scripts.page1_v3.essay_generator import EssayResult

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
# (a) _swap_page_one
# ---------------------------------------------------------------------------

def test_swap_replaces_v2_section():
    template = (
        '<html><head></head><body>'
        '<section class="page page-one">v2 content</section>'
        '<section class="page page-two">untouched</section>'
        '</body></html>'
    )
    v3_section = '<section class="page page-one-v3">v3 content</section>'
    out = v3._swap_page_one(template, v3_section)
    _check("a1 v2 page-one が消える", '<section class="page page-one">' not in out)
    _check("a2 v3 page-one-v3 が入る", 'page-one-v3' in out)
    _check("a3 page-two は手付かず", 'page-two">untouched' in out)


def test_swap_raises_when_no_marker():
    try:
        v3._swap_page_one("<html>no page-one</html>", "<section/>")
    except RuntimeError as e:
        _check("a4 marker 無し → RuntimeError", "not found" in str(e))
        return
    _check("a4 marker 無し → RuntimeError", False, "no exception raised")


# ---------------------------------------------------------------------------
# (b) _archive_path
# ---------------------------------------------------------------------------

def test_archive_path_format():
    p = v3._archive_path(date(2026, 5, 24))
    _check("b1 archive path 形式", p.name == "2026-05-24.html")
    _check("b2 archive ディレクトリ", p.parent.name == "archive")


# ---------------------------------------------------------------------------
# (c) _try_v3_swap: 月次選定未投入 → False
# ---------------------------------------------------------------------------

def test_v3_swap_skipped_when_no_week():
    with tempfile.TemporaryDirectory() as td:
        # 空 pivotal
        pivotal = Path(td) / "p.json"
        pivotal.write_text('{"weeks": {}}', encoding="utf-8")
        # archive ファイル（適当）
        archive = Path(td) / "2026-05-24.html"
        archive.write_text(
            '<html><body><section class="page page-one">v2</section></body></html>',
            encoding="utf-8",
        )

        # _archive_path を上書き
        args = mock.Mock(
            pivotal_path=str(pivotal),
            history_path=str(Path(td) / "h.json"),
            comments_dir=str(Path(td) / "c"),
        )
        with mock.patch.object(v3, "_archive_path", return_value=archive):
            applied = v3._try_v3_swap(date(2026, 5, 24), args)
    _check("c1 未投入週 → applied=False", applied is False)


# ---------------------------------------------------------------------------
# (d) _try_v3_swap: archive 不在 → False
# ---------------------------------------------------------------------------

def test_v3_swap_skipped_when_archive_missing():
    with tempfile.TemporaryDirectory() as td:
        # 実 pivotal を使う（W1 が確実にある）
        args = mock.Mock(
            pivotal_path=None,
            history_path=str(Path(td) / "h.json"),
            comments_dir=str(Path(td) / "c"),
        )
        # archive 不在パス
        with mock.patch.object(v3, "_archive_path",
                                return_value=Path(td) / "missing.html"):
            applied = v3._try_v3_swap(date(2026, 5, 24), args)
    _check("d1 archive 不在 → applied=False", applied is False)


# ---------------------------------------------------------------------------
# (e) _try_v3_swap: 成功パス（mock essay_generator）
# ---------------------------------------------------------------------------

def test_v3_swap_success_with_mocked_essay():
    fake_essay = EssayResult(
        angle_label="日曜 - 全体像",
        daily_question="テスト問い",
        essay_title="テストタイトル",
        body="テスト本文の段落。",
        annotation_label="主要キーワード",
        annotation_body="解説。",
        quote_excerpt="引用。",
        cost_usd=0.05, is_fallback=False,
    )
    with tempfile.TemporaryDirectory() as td:
        archive = Path(td) / "2026-05-24.html"
        archive.write_text(
            '<html><head><style>.x{}</style></head><body>'
            '<section class="page page-one">v2 元の内容</section>'
            '<section class="page page-two">page2 keep</section>'
            '</body></html>',
            encoding="utf-8",
        )
        args = mock.Mock(
            pivotal_path=None,
            history_path=str(Path(td) / "h.json"),
            comments_dir=str(Path(td) / "c"),
        )
        with mock.patch.object(v3, "_archive_path", return_value=archive), \
             mock.patch.object(v3, "generate_essay", return_value=fake_essay):
            applied = v3._try_v3_swap(date(2026, 5, 24), args)
        result_html = archive.read_text(encoding="utf-8")
        # tempdir 削除前に history 存在を確認
        history_exists = (Path(td) / "h.json").exists()
    _check("e1 applied=True", applied is True)
    _check("e2 v2 page-one が swap された",
           'page-one-v3' in result_html and 'v2 元の内容' not in result_html)
    _check("e3 page-two は手付かず", 'page2 keep' in result_html)
    _check("e4 v3 CSS inject 済", '.page-one-v3' in result_html)
    _check("e5 階層 2 問い反映", "テスト問い" in result_html)
    _check("e6 essay が history に保存", history_exists)


# ---------------------------------------------------------------------------
# (f) _run_production: v2 main 失敗時は v3 swap 試みない
# ---------------------------------------------------------------------------

def test_production_skips_v3_when_v2_fails():
    args = mock.Mock(pivotal_path=None, history_path=None, comments_dir=None)
    with mock.patch("importlib.import_module") as imp:
        fake_v2 = mock.Mock()
        fake_v2.main.return_value = 1
        imp.return_value = fake_v2
        with mock.patch.object(v3, "_try_v3_swap") as swap_mock:
            rc = v3._run_production(date(2026, 5, 24), args, v2_passthrough_argv=[])
    _check("f1 v2 rc=1 → v3 rc=1 で返る", rc == 1)
    _check("f2 v2 失敗時 _try_v3_swap が呼ばれない", swap_mock.called is False)


# ---------------------------------------------------------------------------
# (g) _run_production: v3 swap が例外を投げても rc=0（v2 出力残す）
# ---------------------------------------------------------------------------

def test_production_swap_exception_returns_zero():
    args = mock.Mock(pivotal_path=None, history_path=None, comments_dir=None)
    with mock.patch("importlib.import_module") as imp:
        fake_v2 = mock.Mock()
        fake_v2.main.return_value = 0
        imp.return_value = fake_v2
        with mock.patch.object(v3, "_try_v3_swap",
                                side_effect=RuntimeError("boom")):
            rc = v3._run_production(date(2026, 5, 24), args, v2_passthrough_argv=[])
    _check("g1 swap 例外 → rc=0（v2 残す）", rc == 0)


# ---------------------------------------------------------------------------
# (h) CLI parsing
# ---------------------------------------------------------------------------

def test_parse_date_valid():
    d = v3._parse_target_date("2026-05-24")
    _check("h1 valid date parse", d == date(2026, 5, 24))


def test_parse_date_invalid_returns_none():
    d = v3._parse_target_date("not-a-date")
    _check("h2 invalid date → None", d is None)


def test_parse_date_default_today():
    d = v3._parse_target_date(None)
    _check("h3 None → today", d == date.today())


def main() -> int:
    print("regen_front_page_v3 — swap + fallback tests")
    print()
    print("(a) _swap_page_one:")
    test_swap_replaces_v2_section()
    test_swap_raises_when_no_marker()
    print()
    print("(b) _archive_path:")
    test_archive_path_format()
    print()
    print("(c) v3 swap: 未投入週:")
    test_v3_swap_skipped_when_no_week()
    print()
    print("(d) v3 swap: archive 不在:")
    test_v3_swap_skipped_when_archive_missing()
    print()
    print("(e) v3 swap: 成功 mock essay:")
    test_v3_swap_success_with_mocked_essay()
    print()
    print("(f) production: v2 失敗時に v3 skip:")
    test_production_skips_v3_when_v2_fails()
    print()
    print("(g) production: v3 例外 → rc=0:")
    test_production_swap_exception_returns_zero()
    print()
    print("(h) CLI parsing:")
    test_parse_date_valid()
    test_parse_date_invalid_returns_none()
    test_parse_date_default_today()
    print()
    print(f"=== {PASS} passed, {FAIL} failed ===")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
