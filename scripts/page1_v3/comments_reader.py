"""神山さんコメント md の読み込み（Phase 3, 2026-05-23）.

仕様 §4.7：``data/comments/YYYY-MM-DD.md`` を直接編集で投入。自由形式の
markdown（テンプレ無し）。Code 側はパースせず全文をそのまま保持し、
土曜の AI かみやま応答生成（saturday_responder）に渡す。

欠落（神山さんがその日コメントを残さなかった）は許容。リストには含めない。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from .monthly_pivotal import WeekContext, angle_for_day

DEFAULT_COMMENTS_DIR = (
    Path(__file__).resolve().parent.parent.parent / "data" / "comments"
)


@dataclass
class DailyComment:
    """1 日分の神山さんコメント（自由形式 md 全文）."""
    target_date: date
    day_label: str
    angle_label_jp: str
    body: str  # md 全文（前後 strip のみ、構造化しない）

    @property
    def is_empty(self) -> bool:
        return not self.body.strip()


def _read_comment_file(path: Path, target: date) -> DailyComment | None:
    """1 ファイルを読む。欠落・空・I/O 例外なら None."""
    if not path.exists():
        return None
    try:
        body = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not body:
        return None
    day_label, _, angle_label_jp = angle_for_day(target)
    return DailyComment(
        target_date=target,
        day_label=day_label,
        angle_label_jp=angle_label_jp,
        body=body,
    )


def load_week_comments(
    week: WeekContext,
    *,
    comments_dir: Path | None = None,
    include_saturday: bool = False,
) -> list[DailyComment]:
    """週内（日-金 デフォルト）のコメントを日付順で返す。欠落は entry に含めない.

    Parameters
    ----------
    include_saturday :
        通常 False（土曜は AI かみやま応答日でコメント収集対象外）。
        将来「土曜紙面読後のコメント」を扱う場合に True に切替可能な拡張口。
    """
    base = comments_dir or DEFAULT_COMMENTS_DIR
    start, end = week.period  # (日曜, 土曜)
    last_offset = (end - start).days  # 通常 6
    if not include_saturday:
        last_offset -= 1  # 土曜（オフセット 6）を除外
    out: list[DailyComment] = []
    for offset in range(last_offset + 1):
        d = start + timedelta(days=offset)
        path = base / f"{d.isoformat()}.md"
        comment = _read_comment_file(path, d)
        if comment is not None:
            out.append(comment)
    return out
