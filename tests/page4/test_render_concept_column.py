"""Unit tests for _render_page4_concept_column (C55, 2026-06-02).

6/2 朝刊 4 面 concept セクションでマークダウン ** が紙面表示された事象
への対策の renderer 安全網テスト。C52 (1 面論考 renderer) と同パターン
の二段ガードを 4 面 concept にも展開する。

Run::

    python3 -m tests.page4.test_render_concept_column
"""

from __future__ import annotations

import sys

from scripts.regen_front_page_v2 import _render_page4_concept_column

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


def _sample_concept() -> dict:
    return {
        "id": "servant_leadership",
        "name_ja": "サーバントリーダーシップ",
        "name_en": "Servant Leadership",
        "domain": "経営学",
        "thinkers": ["ロバート・グリーンリーフ"],
    }


# ---------------------------------------------------------------------------
# (a) C55 safety net: **bold** → <strong>bold</strong>
# ---------------------------------------------------------------------------

def test_markdown_bold_converted_to_strong():
    essay = (
        "**サーバントリーダーシップ** は権力を握ることではなく、"
        "他者の成長を支える在り方を志向する概念である。"
    )
    out = _render_page4_concept_column(_sample_concept(), essay)
    _check(
        "a1 **bold** → <strong>bold</strong> 変換",
        "<strong>サーバントリーダーシップ</strong>" in out
        and "**サーバントリーダーシップ**" not in out,
        f"got essay 部分: {out[out.find('<p>'):out.find('</p>')+4]!r}",
    )


def test_multiple_bold_in_one_essay():
    essay = "**前提**を疑い、**結論**を再構成する。"
    out = _render_page4_concept_column(_sample_concept(), essay)
    _check(
        "a2 1 段落内に複数 ** があっても全て <strong> に変換",
        out.count("<strong>") == 2
        and "**前提**" not in out
        and "**結論**" not in out,
        f"got essay 部分: {out[out.find('<p>'):out.find('</p>')+4]!r}",
    )


def test_no_markdown_no_strong_tag():
    """マークダウン無しの essay は <strong> が入らない."""
    essay = "現象学とは、意識に現れる事象そのものを記述する哲学的方法である。"
    out = _render_page4_concept_column(_sample_concept(), essay)
    _check(
        "a3 マークダウンなし essay → <strong> が出ない",
        "<strong>" not in out and "現象学" in out,
    )


def test_lone_asterisks_not_misinterpreted():
    """単独 ** だけがある場合は変換対象外（誤マッチ防止）."""
    essay = "脚注の参照記号 ** が概念末尾に現れた場合の処理。"
    out = _render_page4_concept_column(_sample_concept(), essay)
    _check(
        "a4 単独 ** は <strong> 化しない（peer は閉じない）",
        "<strong>" not in out,
        f"got essay 部分: {out[out.find('<p>'):out.find('</p>')+4]!r}",
    )


def test_empty_essay_does_not_crash():
    out = _render_page4_concept_column(_sample_concept(), "")
    _check(
        "a5 空 essay でも crash せず、構造は保たれる",
        "<p></p>" in out and "concept-column" in out,
    )


# ---------------------------------------------------------------------------
# (b) 既存挙動の維持（concept の他フィールドは escape されるだけ）
# ---------------------------------------------------------------------------

def test_concept_fields_still_escaped():
    """concept の name / domain / thinkers は escape のみ（**変換は essay のみ）.

    `**` を含む concept name は実運用で発生しないが、変換が essay
    だけに限定されていることの safety net テスト。
    """
    concept = {
        "id": "x", "name_ja": "<bad>", "name_en": "Y",
        "domain": "Z", "thinkers": ["A"],
    }
    out = _render_page4_concept_column(concept, "normal essay")
    _check(
        "b1 concept.name_ja の <bad> は escape される",
        "&lt;bad&gt;" in out and "<bad>" not in out,
    )


def test_essay_contains_dangerous_html():
    """essay 内の HTML 特殊文字も escape された上で ** → <strong> 変換."""
    essay = "**強調**部分と <script>alert(1)</script> が混在。"
    out = _render_page4_concept_column(_sample_concept(), essay)
    _check(
        "b2 essay 内 <script> は escape、**強調** は <strong> 化",
        "<strong>強調</strong>" in out
        and "&lt;script&gt;" in out
        and "<script>" not in out.replace("</strong>", "").replace(
            "</p>", "").replace("</article>", "").replace("</aside>", "").replace(
            "</h3>", "").replace("</span>", "").replace("</div>", ""),
        f"essay 部分: {out[out.find('<p>'):out.find('</p>')+4]!r}",
    )


def main() -> int:
    print("Page 4 — _render_page4_concept_column tests (C55, 2026-06-02)")
    print()
    print("(a) C55 safety net (markdown **bold** → <strong>):")
    test_markdown_bold_converted_to_strong()
    test_multiple_bold_in_one_essay()
    test_no_markdown_no_strong_tag()
    test_lone_asterisks_not_misinterpreted()
    test_empty_essay_does_not_crash()
    print()
    print("(b) 既存挙動の維持:")
    test_concept_fields_still_escaped()
    test_essay_contains_dangerous_html()
    print()
    print(f"=== {PASS} passed, {FAIL} failed ===")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
