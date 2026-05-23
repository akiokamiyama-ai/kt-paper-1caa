"""土曜紙面下部「来週予告」セクション（Phase 3, 2026-05-23）.

仕様 §4.9：土曜のみ表示、紙面下部 1/4 程度の軽い扱い。来週のテーマ +
7 日間角度一覧を簡潔に表示。来週分が未投入なら placeholder。
"""

from __future__ import annotations

from .monthly_pivotal import WeekContext

# 仕様 §4.9 のサンプル順に揃える（日 → 月 → ... → 土）。
_PREVIEW_DAYS: list[tuple[str, str]] = [
    ("日", "全体像"),
    ("月", "批判的"),
    ("火", "実践者"),
    ("水", "思想家"),
    ("木", "歴史"),
    ("金", "統合＋問い"),
    ("土", "応答（神山さんコメントへ）"),
]


def build_next_week_preview(next_week: WeekContext | None) -> str:
    """HTML フラグメントを返す（``<section>`` でラップ）.

    next_week が None（来月分未投入等）の場合は placeholder セクションを返す。
    全くセクションを出さない選択肢もあるが、仕様 §4.9 は土曜紙面下部の
    定常セクションなので「予告調整中」表示で枠を保つ方が一貫性高い。
    """
    if next_week is None:
        return _placeholder_html()
    items_html = "\n".join(
        f'    <li class="np-row"><span class="np-day">{day}</span>'
        f'<span class="np-angle">{angle}</span></li>'
        for day, angle in _PREVIEW_DAYS
    )
    period_str = (
        f"{next_week.period[0].strftime('%-m/%-d')}〜"
        f"{next_week.period[1].strftime('%-m/%-d')}"
    )
    return f"""<section class="next-week-preview">
  <h3 class="np-banner">来週予告</h3>
  <p class="np-theme">{_esc(next_week.theme)}<span class="np-period">（{period_str}）</span></p>
  <ol class="np-list">
{items_html}
  </ol>
</section>"""


def _placeholder_html() -> str:
    return """<section class="next-week-preview next-week-preview--pending">
  <h3 class="np-banner">来週予告</h3>
  <p class="np-pending">来週分は月次選定セッション後に確定します。</p>
</section>"""


def _esc(s: str) -> str:
    """最小限の HTML escape（renderer.py 側の _esc と独立、依存を避ける）."""
    return (
        (s or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
