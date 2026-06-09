"""archive/{date}.html と data/comments/{date}.md から DayEntry を組み立てる。

C38b (Sprint 9, 2026-06-09)。
"""

from __future__ import annotations

import html as _html
import re
from datetime import date
from pathlib import Path

from .models import DayEntry

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
ARCHIVE_DIR = PROJECT_ROOT / "archive"
COMMENTS_DIR = PROJECT_ROOT / "data" / "comments"

_PAGE_FOUR_RE = re.compile(
    r'<section class="page page-four">(.*?)</section>',
    re.DOTALL,
)
# 「今日の概念」見出し（class="concept-title" の H3 タグ。和名 + <span class="concept-en"> 英名）
_CONCEPT_TITLE_RE = re.compile(
    r'<h3[^>]*class="[^"]*concept-title[^"]*"[^>]*>(.*?)</h3>',
    re.DOTALL,
)
# 概念エッセイ本文（class="concept-essay" の DIV）
_CONCEPT_ESSAY_RE = re.compile(
    r'<div[^>]*class="[^"]*concept-essay[^"]*"[^>]*>(.*?)</div>',
    re.DOTALL,
)

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def _strip_html(text: str) -> str:
    """HTML タグ + entity を平文に。空白圧縮。"""
    no_tags = _TAG_RE.sub(" ", text)
    decoded = _html.unescape(no_tags)
    return _WS_RE.sub(" ", decoded).strip()


def _strip_html_keep_paragraphs(text: str) -> str:
    """段落保持しつつタグ除去。<p>/<br> を改行に変換してから他タグを除去。"""
    # <p> end / <br> → 改行マーカー
    t = re.sub(r"</p\s*>", "\n\n", text, flags=re.IGNORECASE)
    t = re.sub(r"<br\s*/?>", "\n", t, flags=re.IGNORECASE)
    t = _TAG_RE.sub("", t)
    t = _html.unescape(t)
    # 各行 trim、連続空行は 2 つに圧縮
    lines = [ln.strip() for ln in t.split("\n")]
    out: list[str] = []
    blank = 0
    for ln in lines:
        if not ln:
            blank += 1
            if blank <= 1:
                out.append("")
            continue
        blank = 0
        out.append(ln)
    return "\n".join(out).strip()


def extract_page_four(html: str) -> tuple[str, str]:
    """archive HTML から (concept_name, concept_essay) を抽出。

    見つからなければ空文字を返す。LLM 側の defensive。
    """
    m = _PAGE_FOUR_RE.search(html)
    if not m:
        return "", ""
    inner = m.group(1)
    name_m = _CONCEPT_TITLE_RE.search(inner)
    name = _strip_html(name_m.group(1)) if name_m else ""
    essay_m = _CONCEPT_ESSAY_RE.search(inner)
    if essay_m:
        essay = _strip_html_keep_paragraphs(essay_m.group(1))
    else:
        # フォールバック：page-four 全体から平文化（class 名が変わった場合の保険）
        essay = _strip_html_keep_paragraphs(inner)
    return name, essay


def load_day(target: date) -> DayEntry:
    """1 日分を読み込む。ファイルが無くても空 DayEntry を返す（途中欠損許容）。"""
    archive_path = ARCHIVE_DIR / f"{target.isoformat()}.html"
    comments_path = COMMENTS_DIR / f"{target.isoformat()}.md"

    concept_name = ""
    concept_essay = ""
    if archive_path.exists():
        try:
            html = archive_path.read_text(encoding="utf-8")
            concept_name, concept_essay = extract_page_four(html)
        except OSError:
            pass

    comment = ""
    if comments_path.exists():
        try:
            comment = comments_path.read_text(encoding="utf-8").strip()
        except OSError:
            pass

    return DayEntry(
        date=target,
        concept_name=concept_name,
        concept_essay=concept_essay,
        comment=comment,
    )
