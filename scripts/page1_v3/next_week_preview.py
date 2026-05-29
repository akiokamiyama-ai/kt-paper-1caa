"""土曜紙面下部「来週予告」セクション（Phase 3, 2026-05-23）.

仕様 §4.9：土曜のみ表示、紙面下部 1/4 程度の軽い扱い。

C47 (Sprint 8, 2026-05-30): 旧形式の 6 日間角度説明（日=全体像 / 月=批判的 …）は
神山さん「これはいらない」評価で削除。代わりに来週主軸記事の 1 行紹介を出す。
データソースは ``data/monthly_pivotal.json`` の article.title と article.summary。
"""

from __future__ import annotations

from .monthly_pivotal import WeekContext


def build_next_week_preview(next_week: WeekContext | None) -> str:
    """HTML フラグメントを返す（``<section>`` でラップ）.

    next_week が None（来月分未投入等）の場合は placeholder セクションを返す。
    全くセクションを出さない選択肢もあるが、仕様 §4.9 は土曜紙面下部の
    定常セクションなので「予告調整中」表示で枠を保つ方が一貫性高い。

    C47 (2026-05-30): 6 日間角度一覧（np-list / np-row）を削除し、来週主軸記事の
    1 行紹介（np-pivotal）に置換。
    """
    if next_week is None:
        return _placeholder_html()
    period_str = (
        f"{next_week.period[0].strftime('%-m/%-d')}〜"
        f"{next_week.period[1].strftime('%-m/%-d')}"
    )
    pivotal_html = _render_pivotal_intro(next_week)
    return f"""<section class="next-week-preview">
  <h3 class="np-banner">来週予告</h3>
  <p class="np-theme">{_esc(next_week.theme)}<span class="np-period">（{period_str}）</span></p>
{pivotal_html}
</section>"""


def _render_pivotal_intro(week: WeekContext) -> str:
    """来週主軸記事の 1 行紹介を組み立てる (C47).

    article.title + article.summary を素材に、紙面下部 1/4 の枠に収まる
    1 段落の紹介文を出す。LLM は使わず、summary を 120 字目安で truncate して
    そのまま接続する（事前選定済の summary は monthly_pivotal.json で人手調整
    されている前提）。
    """
    article = week.article or {}
    title = (article.get("title") or "").strip()
    summary = (article.get("summary") or "").strip()

    if not title:
        return '  <p class="np-pivotal np-pivotal--pending">主軸記事は調整中。</p>'

    short_title = _shorten_title(title, 70)
    summary_excerpt = _truncate_jp(summary, 120) if summary else ""

    if summary_excerpt:
        body = (
            f'来週は<span class="np-pivotal-title">『{_esc(short_title)}』</span>'
            f'を主軸に、{_esc(summary_excerpt)}'
            f'日本の経営者の眼差しで多角的に読み解きます。'
        )
    else:
        body = (
            f'来週は<span class="np-pivotal-title">『{_esc(short_title)}』</span>'
            f'を主軸に、日本の経営者の眼差しで多角的に読み解きます。'
        )

    return f'  <p class="np-pivotal">{body}</p>'


def _shorten_title(title: str, max_chars: int) -> str:
    """長文 title を句切れで truncate。句切れが見つからなければ hard cut + '…'.

    優先順序：英文の period+space → em-dash → hyphen-space → colon-space → 句点。
    『India is No Longer ... Reshaping The Global Economy』のような副題付き
    タイトルを、本筋だけに丸める。
    """
    if len(title) <= max_chars:
        return title
    for sep in (". ", " — ", " - ", ": ", "。"):
        idx = title.find(sep, max_chars // 3, max_chars)
        if idx > 0:
            return title[:idx].rstrip(" .")
    return title[: max_chars - 1].rstrip() + "…"


def _truncate_jp(text: str, max_chars: int) -> str:
    """日本語テキストを句点で truncate。残らなければ '…' 付き hard cut.

    末尾の句点 / 読点があれば前後の繋ぎが読みやすい『〜になった。』の形で残す。
    """
    if len(text) <= max_chars:
        return text
    cut = text[:max_chars]
    for sep in ("。", "．"):
        idx = cut.rfind(sep)
        if idx >= max_chars // 2:
            return cut[: idx + 1]
    return cut.rstrip() + "…"


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
