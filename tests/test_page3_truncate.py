"""第3面 item 本文の文字数上限 (C164, Sprint 13, 2026-08-15).

背景
----
3 面は運用開始（2026-04-25）以来 **一度も truncate していなかった**。通常の
RSS description は 800 字以内に収まるため顕在化していなかったが、8/16 紙面で
Atlas Obscura のリスト記事が **17,179 字**そのまま流し込まれてグリッドが崩れた。

旧第5面のセレンディピティ枠は 300 字 truncate していたが、C155 で枠を 3 面へ
移した際、3 面の renderer には truncate が無かったため制限が失われた。
**SER 枠固有ではなく 3 面 6 枠すべてに上限が無い**のが真因。

Tests:
  a) 上限を超える description が truncate される
  b) 短い description は無改変（不自然な切れ方をしない）
  c) 文末（。．.）優先で切れる
  d) 6 枠すべてに同じ上限がかかる（SER も他 5 枠と同格）
  e) 境界値
  f) 回帰: renderer に truncate が入っていること

Run::

    python3 -m tests.test_page3_truncate
"""

from __future__ import annotations

import re
import sys

from scripts.regen_front_page_v2 import (
    PAGE3_DESC_MAX_CHARS,
    _render_page3_item,
    build_page_three_v2,
)
from scripts.selector.page3 import DISPLAY_SLOTS, RegionSelection

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


def _body(html: str) -> str:
    """レンダリング結果から item 本文（<p>）を抜く。"""
    m = re.search(r"</h5>\s*<p>(.*?)</p>", html, re.S)
    return re.sub(r"<[^>]+>", "", m.group(1)).strip() if m else ""


def _render(desc: str, region: str = "R1") -> str:
    return _render_page3_item(
        {"title": "T", "description": desc, "source_name": "S",
         "url": "https://example.test/x"},
        region,
    )


# ---------------------------------------------------------------------------
# (a) 長文の truncate
# ---------------------------------------------------------------------------

def test_atlas_obscura_case_truncated():
    """再発防止: 17,000 字級のリスト記事が上限内に収まること."""
    desc = ("Catacombs—underground rooms and tunnels used as cemeteries—"
            "date back to first-century Rome. ") * 190
    out = _body(_render(desc))
    _check(f"a1 17,000 字級が上限 {PAGE3_DESC_MAX_CHARS} 字内に収まる",
           len(out) <= PAGE3_DESC_MAX_CHARS + 1,
           f"入力{len(desc):,} → 出力{len(out)}")
    _check("a2 出力が空にならない", len(out) > 50, f"got {len(out)}")


def test_japanese_long_text_truncated():
    desc = "これは日本語の説明文です。" * 80
    out = _body(_render(desc))
    _check("a3 日本語長文も上限内",
           len(out) <= PAGE3_DESC_MAX_CHARS + 1, f"got {len(out)}")


def test_no_upper_bound_regression():
    """上限が実質無効化されていないこと（巨大入力がそのまま出ない）."""
    out = _body(_render("x" * 50000))
    _check("a4 50,000 字入力でも上限内",
           len(out) <= PAGE3_DESC_MAX_CHARS + 1, f"got {len(out)}")


# ---------------------------------------------------------------------------
# (b) 短文は無改変
# ---------------------------------------------------------------------------

def test_short_description_unchanged():
    desc = "短い概要。"
    _check("b1 短文はそのまま（… が付かない）",
           _body(_render(desc)) == desc, f"got {_body(_render(desc))!r}")


def test_medium_description_unchanged():
    desc = "あ" * (PAGE3_DESC_MAX_CHARS - 50)
    _check("b2 上限未満はそのまま", _body(_render(desc)) == desc)


def test_empty_description():
    _check("b3 空 description で例外を出さない / 空を返す",
           _body(_render("")) == "")


def test_missing_description_key():
    html = _render_page3_item(
        {"title": "T", "source_name": "S", "url": "https://x/"}, "R1")
    _check("b4 description キー欠落でも落ちない", "<p></p>" in html or _body(html) == "")


# ---------------------------------------------------------------------------
# (c) 文末優先で切れる
# ---------------------------------------------------------------------------

def test_cuts_at_sentence_boundary_ja():
    desc = "これは日本語の説明文です。" * 80
    out = _body(_render(desc))
    _check("c1 日本語は句点で切れる（… にならない）",
           out.endswith("。"), f"末尾={out[-12:]!r}")


def test_cuts_at_sentence_boundary_en():
    desc = "This is an English sentence about the topic. " * 40
    out = _body(_render(desc))
    _check("c2 英語はピリオドで切れる", out.endswith("."), f"末尾={out[-14:]!r}")


def test_ellipsis_when_no_sentence_break():
    """句点が無い場合のみ … で打ち切る."""
    out = _body(_render("x" * 900))
    _check("c3 文末が無ければ … を付ける", out.endswith("…"), f"末尾={out[-10:]!r}")


# ---------------------------------------------------------------------------
# (d) 6 枠すべてに同じ上限（SER も同格）
# ---------------------------------------------------------------------------

def test_all_six_slots_truncated():
    """C155 の設計方針「SER 枠も他 5 記事と同格」を文字数でも守る."""
    long_desc = "これは長い説明文です。" * 100
    selections = {
        slot: RegionSelection(
            region=slot,
            article={"title": f"T{slot}", "description": long_desc,
                     "source_name": "S", "url": f"https://x/{slot}"},
            final_score=50, fallback_reason=None,
        )
        for slot in DISPLAY_SLOTS
    }
    html = build_page_three_v2(selections)
    bodies = [
        re.sub(r"<[^>]+>", "", m).strip()
        for m in re.findall(r"</h5>\s*<p>(.*?)</p>", html, re.S)
    ]
    _check("d1 6 枠すべてレンダリングされる", len(bodies) == 6, f"got {len(bodies)}")
    over = [len(b) for b in bodies if len(b) > PAGE3_DESC_MAX_CHARS + 1]
    _check("d2 6 枠すべてが上限内（SER 枠も含む）", not over, f"超過={over}")


def test_ser_slot_same_limit_as_regions():
    long_desc = "同じ長さの説明文です。" * 100
    r1 = _body(_render(long_desc, "R1"))
    ser = _body(_render(long_desc, "SER"))
    _check("d3 SER 枠と R1 枠で truncate 結果が同一（同格の担保）",
           len(r1) == len(ser), f"R1={len(r1)}, SER={len(ser)}")


# ---------------------------------------------------------------------------
# (e) 境界値
# ---------------------------------------------------------------------------

def test_exactly_at_limit():
    desc = "あ" * PAGE3_DESC_MAX_CHARS
    _check("e1 ちょうど上限は無改変", _body(_render(desc)) == desc)


def test_one_over_limit():
    out = _body(_render("あ" * (PAGE3_DESC_MAX_CHARS + 1)))
    _check("e2 上限 +1 は truncate される",
           len(out) <= PAGE3_DESC_MAX_CHARS + 1 and out.endswith("…"),
           f"got len={len(out)}")


def test_limit_constant_sane():
    _check("e3 上限が実測 p90 (458) 前後の実用値",
           200 <= PAGE3_DESC_MAX_CHARS <= 800, f"got {PAGE3_DESC_MAX_CHARS}")


# ---------------------------------------------------------------------------
# (f) 回帰防止
# ---------------------------------------------------------------------------

def test_renderer_actually_truncates():
    """renderer が description を素通ししていないこと（C164 の回帰防止）."""
    import inspect
    src = inspect.getsource(_render_page3_item)
    _check("f1 renderer が _truncate_to_chars を呼ぶ",
           "_truncate_to_chars" in src)
    _check("f2 素の article.get('description') 直代入が残っていない",
           'description = article.get("description") or ""' not in src)


def main() -> int:
    print("第3面 文字数上限 tests (C164, Sprint 13, 2026-08-15)")
    print(f"  PAGE3_DESC_MAX_CHARS = {PAGE3_DESC_MAX_CHARS}")
    print()
    print("(a) 長文の truncate:")
    test_atlas_obscura_case_truncated()
    test_japanese_long_text_truncated()
    test_no_upper_bound_regression()
    print()
    print("(b) 短文は無改変:")
    test_short_description_unchanged()
    test_medium_description_unchanged()
    test_empty_description()
    test_missing_description_key()
    print()
    print("(c) 文末優先:")
    test_cuts_at_sentence_boundary_ja()
    test_cuts_at_sentence_boundary_en()
    test_ellipsis_when_no_sentence_break()
    print()
    print("(d) 6 枠すべて同格:")
    test_all_six_slots_truncated()
    test_ser_slot_same_limit_as_regions()
    print()
    print("(e) 境界値:")
    test_exactly_at_limit()
    test_one_over_limit()
    test_limit_constant_sane()
    print()
    print("(f) 回帰防止:")
    test_renderer_actually_truncates()
    print()
    print(f"=== {PASS} passed, {FAIL} failed ===")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
