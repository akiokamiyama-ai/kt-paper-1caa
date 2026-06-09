"""Data structures for the note generation pipeline (C38b)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


@dataclass
class DayEntry:
    """1 日分の入力データ。論考 + コメント。"""

    date: date
    concept_name: str          # page IV の「今日の概念」名
    concept_essay: str         # page IV の概念エッセイ本文（HTML タグ除去後）
    comment: str               # data/comments/{date}.md の中身（空文字あり）

    @property
    def has_essay(self) -> bool:
        return bool(self.concept_essay.strip())

    @property
    def has_comment(self) -> bool:
        return bool(self.comment.strip())


@dataclass
class NoteContext:
    """1 週間分の集約。LLM プロンプト構築の入力。"""

    start_date: date
    end_date: date
    label: str                 # 出力 filename のベース（例: "W1", "2026-W23"）
    days: list[DayEntry] = field(default_factory=list)


@dataclass
class GeneratedNote:
    """LLM 出力 + メタ情報。"""

    label: str
    body: str                  # 草稿 Markdown 全文
    model: str
    input_tokens: int
    output_tokens: int
    cache_creation_tokens: int
    cache_read_tokens: int
    cost_usd: float
