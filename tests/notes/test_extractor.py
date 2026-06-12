"""Unit tests for scripts/notes/extractor.py (C80d M5).

Sprint 9 Fable レビュー M5 対応。``scripts/notes/`` 一式（~970 行）に
テストが 0 件だった状態を解消する第二弾（第一弾は test_generate.py で
label validation + sentinel sanitization をカバー）。

本テストは extractor の純関数を対象：

- ``_strip_html`` / ``_strip_html_keep_paragraphs``
- ``extract_page_four(html) → (concept_name, concept_essay)``
- ``load_day(target_date) → DayEntry``（fixture HTML + comment ファイルで）

archive HTML の構造変化で W 集約が静かに空入力化するリスクを抑える
（M5 観察：load_day は欠損許容設計で気づきにくい）。

Run::

    python3 -m tests.notes.test_extractor
"""

from __future__ import annotations

import sys
import tempfile
from datetime import date
from pathlib import Path

from scripts.notes import extractor

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
# (a) _strip_html / _strip_html_keep_paragraphs
# ---------------------------------------------------------------------------

def test_strip_html_removes_tags():
    out = extractor._strip_html("<p>Hello <b>world</b></p>")
    _check("a1 _strip_html: tags removed, whitespace collapsed",
           out == "Hello world", f"got {out!r}")


def test_strip_html_decodes_entities():
    out = extractor._strip_html("&quot;Hello&quot; &amp; <i>world</i>")
    _check("a2 _strip_html: entities decoded",
           out == '"Hello" & world', f"got {out!r}")


def test_strip_html_empty_input():
    _check("a3 _strip_html(''): empty",
           extractor._strip_html("") == "")


def test_strip_html_keep_paragraphs_preserves_breaks():
    """``</p>`` と ``<br>`` は改行に変換される."""
    html = "<p>First para</p><p>Second para</p>"
    out = extractor._strip_html_keep_paragraphs(html)
    _check(
        "a4 _strip_html_keep_paragraphs: </p> が空行に変換、複数段落保持",
        "First para" in out and "Second para" in out
        and "\n" in out,
        f"got {out!r}",
    )


def test_strip_html_keep_paragraphs_collapses_blank_runs():
    """連続空行は 2 つに圧縮される."""
    html = "<p>A</p><p></p><p></p><p>B</p>"
    out = extractor._strip_html_keep_paragraphs(html)
    # 空行は最大 1 つの空行に圧縮（連続空行 ≤ 1）
    _check(
        "a5 _strip_html_keep_paragraphs: 連続空行 ≤ 1",
        "\n\n\n" not in out,
        f"got {out!r}",
    )


# ---------------------------------------------------------------------------
# (b) extract_page_four
# ---------------------------------------------------------------------------

_SAMPLE_PAGE_FOUR = """<!DOCTYPE html>
<html>
<body>
<section class="page page-one">page 1 content</section>
<section class="page page-four">
  <article class="concept-column">
    <h3 class="concept-title">
      心理的安全性
      <span class="concept-en">Psychological Safety</span>
    </h3>
    <div class="concept-essay">
      <p>これは概念エッセイの本文段落である。エイミー・エドモンドソンが提唱した。</p>
    </div>
  </article>
  <aside class="academic-column">
    <div class="item"><h5>学術記事 1</h5></div>
  </aside>
</section>
</body>
</html>"""


def test_extract_page_four_returns_concept_name_and_essay():
    name, essay = extractor.extract_page_four(_SAMPLE_PAGE_FOUR)
    _check(
        "b1 extract_page_four: 概念名（和名 + 英名）抽出",
        "心理的安全性" in name and "Psychological Safety" in name,
        f"got name={name!r}",
    )
    _check(
        "b2 extract_page_four: エッセイ本文抽出",
        "エイミー・エドモンドソン" in essay,
        f"got essay={essay[:60]!r}",
    )


def test_extract_page_four_no_section_returns_empty():
    out = extractor.extract_page_four(
        "<html><body>no page-four here</body></html>"
    )
    _check(
        "b3 page-four section 無 → ('', '')",
        out == ("", ""),
        f"got {out}",
    )


def test_extract_page_four_no_concept_title_returns_empty_name():
    html = """<section class="page page-four">
        <div class="concept-essay"><p>essay body</p></div>
    </section>"""
    name, essay = extractor.extract_page_four(html)
    _check(
        "b4 concept-title 無 → name='', essay は抽出される",
        name == "" and "essay body" in essay,
        f"got name={name!r} essay={essay[:60]!r}",
    )


def test_extract_page_four_no_concept_essay_falls_back_to_full():
    """concept-essay div が無い場合、page-four 全体を平文化（fallback）."""
    html = """<section class="page page-four">
        <h3 class="concept-title">テスト概念</h3>
        <p>任意の本文。</p>
    </section>"""
    name, essay = extractor.extract_page_four(html)
    _check(
        "b5 concept-essay 無 → page-four 全体を平文化 fallback",
        name == "テスト概念" and "任意の本文" in essay,
        f"got name={name!r} essay={essay[:60]!r}",
    )


# ---------------------------------------------------------------------------
# (c) load_day
# ---------------------------------------------------------------------------

def test_load_day_returns_empty_when_files_missing():
    """archive HTML / comment 両方欠落 → 空 DayEntry."""
    with tempfile.TemporaryDirectory() as td:
        archive_dir = Path(td) / "archive"
        comments_dir = Path(td) / "data" / "comments"
        archive_dir.mkdir(parents=True)
        comments_dir.mkdir(parents=True)

        orig_a = extractor.ARCHIVE_DIR
        orig_c = extractor.COMMENTS_DIR
        extractor.ARCHIVE_DIR = archive_dir
        extractor.COMMENTS_DIR = comments_dir
        try:
            d = extractor.load_day(date(2026, 6, 12))
        finally:
            extractor.ARCHIVE_DIR = orig_a
            extractor.COMMENTS_DIR = orig_c

    _check(
        "c1 archive + comment 欠落 → 空 DayEntry",
        d.concept_name == "" and d.concept_essay == "" and d.comment == "",
        f"got name={d.concept_name!r} essay_len={len(d.concept_essay)} "
        f"comment_len={len(d.comment)}",
    )
    _check(
        "c2 has_essay / has_comment 両方 False",
        not d.has_essay and not d.has_comment,
    )


def test_load_day_loads_essay_and_comment():
    """archive HTML + comment ファイル両方ある case."""
    with tempfile.TemporaryDirectory() as td:
        archive_dir = Path(td) / "archive"
        comments_dir = Path(td) / "data" / "comments"
        archive_dir.mkdir(parents=True)
        comments_dir.mkdir(parents=True)

        target = date(2026, 6, 12)
        (archive_dir / f"{target.isoformat()}.html").write_text(
            _SAMPLE_PAGE_FOUR, encoding="utf-8",
        )
        (comments_dir / f"{target.isoformat()}.md").write_text(
            "本人のコメント。\n複数行 OK。\n", encoding="utf-8",
        )

        orig_a = extractor.ARCHIVE_DIR
        orig_c = extractor.COMMENTS_DIR
        extractor.ARCHIVE_DIR = archive_dir
        extractor.COMMENTS_DIR = comments_dir
        try:
            d = extractor.load_day(target)
        finally:
            extractor.ARCHIVE_DIR = orig_a
            extractor.COMMENTS_DIR = orig_c

    _check(
        "c3 load_day: 概念名 + エッセイ + コメントすべて取得",
        "心理的安全性" in d.concept_name
        and "エイミー・エドモンドソン" in d.concept_essay
        and "本人のコメント。" in d.comment,
        f"got name={d.concept_name!r} essay_len={len(d.concept_essay)} "
        f"comment_first={d.comment.splitlines()[0] if d.comment else None!r}",
    )
    _check(
        "c4 has_essay / has_comment 両方 True",
        d.has_essay and d.has_comment,
    )


def test_load_day_partial_only_comment():
    """archive 欠落 / comment のみ存在 → essay 空、comment 有."""
    with tempfile.TemporaryDirectory() as td:
        archive_dir = Path(td) / "archive"
        comments_dir = Path(td) / "data" / "comments"
        archive_dir.mkdir(parents=True)
        comments_dir.mkdir(parents=True)

        target = date(2026, 6, 12)
        (comments_dir / f"{target.isoformat()}.md").write_text(
            "コメントだけ", encoding="utf-8",
        )

        orig_a = extractor.ARCHIVE_DIR
        orig_c = extractor.COMMENTS_DIR
        extractor.ARCHIVE_DIR = archive_dir
        extractor.COMMENTS_DIR = comments_dir
        try:
            d = extractor.load_day(target)
        finally:
            extractor.ARCHIVE_DIR = orig_a
            extractor.COMMENTS_DIR = orig_c

    _check(
        "c5 archive 欠落 / comment 有 → has_essay=False, has_comment=True",
        not d.has_essay and d.has_comment and d.comment == "コメントだけ",
        f"got essay_len={len(d.concept_essay)} comment={d.comment!r}",
    )


def main() -> int:
    print("scripts/notes/extractor unit tests (C80d M5)")
    print()

    print("(a) _strip_html / _strip_html_keep_paragraphs:")
    test_strip_html_removes_tags()
    test_strip_html_decodes_entities()
    test_strip_html_empty_input()
    test_strip_html_keep_paragraphs_preserves_breaks()
    test_strip_html_keep_paragraphs_collapses_blank_runs()

    print()
    print("(b) extract_page_four:")
    test_extract_page_four_returns_concept_name_and_essay()
    test_extract_page_four_no_section_returns_empty()
    test_extract_page_four_no_concept_title_returns_empty_name()
    test_extract_page_four_no_concept_essay_falls_back_to_full()

    print()
    print("(c) load_day:")
    test_load_day_returns_empty_when_files_missing()
    test_load_day_loads_essay_and_comment()
    test_load_day_partial_only_comment()

    print()
    print(f"=== {PASS} passed, {FAIL} failed ===")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
