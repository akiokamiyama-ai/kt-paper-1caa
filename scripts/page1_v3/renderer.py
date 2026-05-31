"""Phase 3 1 面 HTML レンダリング（2026-05-23）.

EssayResult / SaturdayResult を 1 面 ``<section class="page page-one-v3">``
HTML に組み立てる。3 階層タイトル + dropcap + 3 段組 + 用語解説 box-out +
主軸記事引用 box の HTML/CSS をここに集約。

v2 の helper（``_esc`` 相当）は import せず、renderer 内に小さく内包して
依存を最小化する（v2 を残す前提なので、共用ヘッダ依存を増やさない方針）。

CSS は ``PAGE_ONE_V3_CSS`` 定数として export し、main 側で template に
inject する。
"""

from __future__ import annotations

import re
from datetime import date

from .essay_generator import EssayResult
from .monthly_pivotal import WeekContext
from .saturday_responder import SaturdayResult

# ----------------------------------------------------------------------------
# HTML helpers
# ----------------------------------------------------------------------------


def _esc(s: str) -> str:
    return (
        (s or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


_MARKDOWN_BOLD_RE = re.compile(r"\*\*([^*\n]+?)\*\*")


def _paragraphs_html(body: str) -> str:
    """``\\n\\n`` で段落分割して ``<p>`` 列にする。先頭段落に dropcap クラス付与.

    C52 (Sprint 8, 2026-06-01) — LLM がマークダウン ``**bold**`` を本文に混ぜた
    場合の safety net として ``<strong>`` 変換を入れる。プロンプト側（C52
    【マークダウン記号の絶対禁止】）で 1 次対策、ここで 2 段目のガード。
    """
    if not body:
        return ""
    parts = [p.strip() for p in body.split("\n\n") if p.strip()]
    if not parts:
        return ""
    out: list[str] = []
    for i, para in enumerate(parts):
        cls = ' class="lede"' if i == 0 else ""
        # 段落内の単一改行は <br> に
        para_html = _esc(para).replace("\n", "<br>")
        # C52 safety net: **bold** → <strong>bold</strong>
        para_html = _MARKDOWN_BOLD_RE.sub(r"<strong>\1</strong>", para_html)
        out.append(f"<p{cls}>{para_html}</p>")
    return "\n".join(out)


def _pivotal_article_html(week: WeekContext, quote_excerpt: str) -> str:
    """主軸記事ボックス（タイトル + メタ + 引用範囲）."""
    a = week.article
    title = _esc(a.get("title") or "")
    url = _esc(a.get("url") or "")
    source = _esc(a.get("source") or "")
    author = _esc(a.get("author") or "")
    published = _esc(a.get("published") or "")
    meta_bits = [b for b in (source, author, published) if b]
    meta_html = " · ".join(meta_bits)
    title_html = (
        f'<a href="{url}" target="_blank" rel="noopener noreferrer">{title}</a>'
        if url else title
    )
    quote_html = _esc(quote_excerpt).replace("\n", "<br>") if quote_excerpt else ""
    quote_block = (
        f'<blockquote class="pivotal-quote">{quote_html}</blockquote>'
        if quote_html else ""
    )
    return f"""<aside class="pivotal-article">
  <div class="pivotal-heading">本週の主軸記事</div>
  <p class="pivotal-title">{title_html}</p>
  <p class="pivotal-meta">{meta_html}</p>
  {quote_block}
</aside>"""


def _annotation_html(label: str, body: str) -> str:
    return f"""<aside class="annotation">
  <h3 class="annotation-label">{_esc(label)}</h3>
  <p class="annotation-body">{_esc(body)}</p>
</aside>"""


def _theme_banner_html(week: WeekContext) -> str:
    return (
        f'<div class="theme-banner">'
        f'<span class="tb-label">今週のテーマ</span>'
        f'<span class="tb-theme">{_esc(week.theme)}</span>'
        f'<span class="tb-period">'
        f'（{week.period[0].strftime("%-m/%-d")}〜{week.period[1].strftime("%-m/%-d")}）'
        f'</span></div>'
    )


# ----------------------------------------------------------------------------
# Section renderers
# ----------------------------------------------------------------------------


def _render_essay_section(essay: EssayResult) -> str:
    """日-金論考の本文セクション（3 階層タイトル + 本文 + 用語解説）."""
    daily_q_html = _esc(essay.daily_question)
    title_html = _esc(essay.essay_title)
    angle_html = _esc(essay.angle_label)
    body_html = _paragraphs_html(essay.body)
    annotation = _annotation_html(essay.annotation_label, essay.annotation_body)
    fallback_class = " essay--fallback" if essay.is_fallback else ""
    return f"""<article class="essay-section{fallback_class}">
  <div class="essay-tier1">{angle_html}</div>
  <h1 class="essay-tier2 daily-question">{daily_q_html}</h1>
  <h2 class="essay-tier3 essay-title">{title_html}</h2>
  <div class="essay-body">
{body_html}
  </div>
  {annotation}
</article>"""


def _render_saturday_section(sat: SaturdayResult) -> str:
    """土曜応答セクション（コメント抜粋 + AIかみやま応答）."""
    daily_q = _esc(sat.daily_question)
    daily_q_html = (
        f'<h1 class="essay-tier2 daily-question">{daily_q}</h1>' if daily_q else ""
    )
    title_html = _esc(sat.response_title)
    angle_html = _esc(sat.angle_label)
    body_html = _paragraphs_html(sat.response_body)
    fallback_class = " essay--fallback" if sat.is_fallback else ""
    if sat.comments_digest:
        digest_html = (
            '<aside class="comments-digest">'
            '<h3 class="cd-heading">この一週間、神山さんからの便り</h3>'
            f'<div class="cd-body">{_paragraphs_html(sat.comments_digest)}</div>'
            '</aside>'
        )
    else:
        digest_html = ""
    byline = '<p class="ai-byline">— AIかみやま</p>'
    return f"""<article class="essay-section saturday-response{fallback_class}">
  <div class="essay-tier1">{angle_html}</div>
  {daily_q_html}
  <h2 class="essay-tier3 essay-title">{title_html}</h2>
  {digest_html}
  <div class="essay-body response-body">
{body_html}
  </div>
  {byline}
</article>"""


# ----------------------------------------------------------------------------
# Public API
# ----------------------------------------------------------------------------


def render_page_one_v3(
    target_date: date,
    week: WeekContext,
    main_section: EssayResult | SaturdayResult,
    next_week_preview_html: str | None = None,
) -> str:
    """1 面 ``<section>`` HTML を返す.

    Parameters
    ----------
    target_date : date
        対象日（HTML 内 data 属性として埋め込み、デバッグ用）。
    week : WeekContext
        当該週の文脈（主軸記事 + theme + 期間）。
    main_section : EssayResult | SaturdayResult
        日-金は EssayResult、土は SaturdayResult。型で出し分け。
    next_week_preview_html : str | None
        土曜のみ非 None。日-金は None で来週予告非表示。
    """
    theme_banner = _theme_banner_html(week)
    if isinstance(main_section, SaturdayResult):
        section_html = _render_saturday_section(main_section)
        pivotal_quote = ""  # 土曜は本文側に digest があるため引用は省略
    else:
        section_html = _render_essay_section(main_section)
        pivotal_quote = main_section.quote_excerpt
    pivotal_html = _pivotal_article_html(week, pivotal_quote)
    preview_html = (
        f"\n  {next_week_preview_html}" if next_week_preview_html else ""
    )
    date_attr = target_date.isoformat()
    return f"""<section class="page page-one-v3" data-date="{date_attr}">
  <div class="page-banner"><span class="pg-num">— Page I —</span> Essay &amp; Pivotal · A Week with One Question</div>
  {theme_banner}
  <div class="page-one-v3-content">
    {section_html}
    {pivotal_html}
  </div>{preview_html}
</section>"""


# ============================================================================
# CSS — main から template 末尾に inject される
# ============================================================================

PAGE_ONE_V3_CSS = """
/* ============================================================
   Page One v3 — 案 C 統合型 1 面再設計（Phase 3, 2026-05-23）
   3 階層タイトル / dropcap / 3 段組 / 用語解説 box-out /
   主軸記事引用 box / 土曜応答 / 来週予告
   ============================================================ */

.page-one-v3 {
  font-family: 'Noto Serif JP', 'Old Standard TT', 'Times New Roman', serif;
}
.page-one-v3 .theme-banner {
  font-family: 'Playfair Display', serif;
  text-align: center;
  margin: 16px 0 24px;
  padding: 12px 16px;
  border-top: 2px double #222;
  border-bottom: 2px double #222;
  letter-spacing: 0.08em;
}
.page-one-v3 .theme-banner .tb-label {
  font-size: 11px;
  text-transform: uppercase;
  color: #666;
  margin-right: 12px;
}
.page-one-v3 .theme-banner .tb-theme {
  font-size: 20px;
  font-weight: 700;
  color: #111;
}
.page-one-v3 .theme-banner .tb-period {
  font-size: 12px;
  color: #888;
  margin-left: 8px;
}

.page-one-v3-content {
  display: grid;
  grid-template-columns: 3fr 1fr;
  gap: 32px;
  align-items: start;
}
@media (max-width: 900px) {
  .page-one-v3-content { grid-template-columns: 1fr; }
}

/* ---- 3 階層タイトル ---- */
.page-one-v3 .essay-tier1 {
  font-family: 'Playfair Display', serif;
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.18em;
  color: #888;
  margin-bottom: 8px;
}
.page-one-v3 .essay-tier2.daily-question {
  /* 階層 2: 日替わりの問い — 1 面で最も目立つ要素 */
  font-family: 'Noto Serif JP', serif;
  font-size: 30px;
  font-weight: 700;
  line-height: 1.45;
  color: #111;
  margin: 0 0 14px;
}
.page-one-v3 .essay-tier3.essay-title {
  font-family: 'Noto Serif JP', serif;
  font-size: 18px;
  font-weight: 600;
  color: #333;
  margin: 0 0 24px;
  padding-bottom: 12px;
  border-bottom: 1px solid #ccc;
}

/* ---- 論考本文：3 段組 + dropcap ---- */
.page-one-v3 .essay-body {
  column-count: 3;
  column-gap: 28px;
  column-rule: 1px solid #eee;
  font-size: 15px;
  line-height: 1.85;
  text-align: justify;
}
@media (max-width: 900px) {
  .page-one-v3 .essay-body { column-count: 1; }
}
.page-one-v3 .essay-body p {
  margin: 0 0 12px;
  text-indent: 1em;
}
.page-one-v3 .essay-body p.lede {
  text-indent: 0;
}
.page-one-v3 .essay-body p.lede::first-letter {
  float: left;
  font-family: 'Playfair Display', serif;
  font-size: 58px;
  line-height: 0.9;
  font-weight: 700;
  padding: 4px 8px 0 0;
  color: #222;
}

/* ---- 用語解説 box-out ---- */
.page-one-v3 .annotation {
  margin: 32px 0 0;
  padding: 14px 18px;
  background: rgba(0, 0, 0, 0.02);
  border-left: 3px solid #888;
}
.page-one-v3 .annotation-label {
  font-family: 'Playfair Display', serif;
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.15em;
  margin: 0 0 8px;
  color: #555;
}
.page-one-v3 .annotation-body {
  font-size: 13px;
  line-height: 1.75;
  color: #333;
  margin: 0;
}

/* ---- 主軸記事ボックス（右カラム）---- */
.page-one-v3 .pivotal-article {
  padding: 16px 18px;
  background: #fafafa;
  border: 1px solid #ddd;
  font-size: 13px;
  line-height: 1.7;
}
.page-one-v3 .pivotal-heading {
  font-family: 'Playfair Display', serif;
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.18em;
  color: #888;
  margin-bottom: 8px;
}
.page-one-v3 .pivotal-title {
  font-family: 'Noto Serif JP', serif;
  font-weight: 700;
  font-size: 14px;
  margin: 0 0 6px;
  line-height: 1.5;
}
.page-one-v3 .pivotal-title a {
  color: inherit;
  text-decoration: none;
  border-bottom: 1px dotted #888;
}
.page-one-v3 .pivotal-meta {
  font-size: 11px;
  color: #777;
  margin: 0 0 10px;
}
.page-one-v3 .pivotal-quote {
  margin: 12px 0 0;
  padding: 10px 12px;
  font-size: 12.5px;
  line-height: 1.75;
  color: #333;
  border-left: 2px solid #aaa;
  background: rgba(0, 0, 0, 0.015);
  quotes: "「" "」";
}
.page-one-v3 .pivotal-quote::before { content: open-quote; }
.page-one-v3 .pivotal-quote::after { content: close-quote; }

/* ---- 土曜応答セクション ---- */
.page-one-v3 .saturday-response .comments-digest {
  margin: 16px 0 24px;
  padding: 14px 18px;
  background: rgba(0, 0, 0, 0.03);
  border-top: 1px solid #ccc;
  border-bottom: 1px solid #ccc;
}
.page-one-v3 .saturday-response .cd-heading {
  font-family: 'Playfair Display', serif;
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.15em;
  color: #666;
  margin: 0 0 10px;
}
.page-one-v3 .saturday-response .cd-body {
  font-size: 13px;
  line-height: 1.75;
  color: #333;
}
.page-one-v3 .saturday-response .cd-body p {
  margin: 0 0 8px;
}
.page-one-v3 .saturday-response .ai-byline {
  font-size: 11px;
  color: #888;
  text-align: right;
  font-style: italic;
  margin-top: 12px;
}

/* ---- 来週予告（土曜下部）---- */
.page-one-v3 + .next-week-preview,
.page-one-v3 .next-week-preview {
  margin: 36px 0 0;
  padding: 18px 20px;
  background: #f8f8f8;
  border: 1px dashed #bbb;
}
.next-week-preview .np-banner {
  font-family: 'Playfair Display', serif;
  font-size: 12px;
  text-transform: uppercase;
  letter-spacing: 0.18em;
  color: #555;
  margin: 0 0 10px;
}
.next-week-preview .np-theme {
  font-family: 'Noto Serif JP', serif;
  font-weight: 700;
  font-size: 16px;
  margin: 0 0 12px;
}
.next-week-preview .np-period {
  font-size: 12px;
  color: #888;
  margin-left: 8px;
  font-weight: 400;
}
/* C47 (Sprint 8, 2026-05-30): 旧 .np-list / .np-row / .np-day / .np-angle は
   6 日間角度説明用だったが「いらない」評価で削除。.np-pivotal で主軸記事の
   1 行紹介を出す。 */
.next-week-preview .np-pivotal {
  font-size: 13px;
  line-height: 1.8;
  color: #333;
  margin: 0;
  padding: 12px 14px;
  background: #fff;
  border-left: 3px solid #c0a060;
  text-align: justify;
}
.next-week-preview .np-pivotal-title {
  font-weight: 700;
  color: #1a1a1a;
}
.next-week-preview .np-pivotal--pending {
  color: #888;
  font-style: italic;
  border-left-color: #ddd;
}
.next-week-preview--pending .np-pending {
  font-size: 12px;
  color: #888;
  margin: 0;
}

/* ---- fallback 体裁（休載表示）---- */
.page-one-v3 .essay--fallback .essay-body {
  color: #888;
  font-style: italic;
}
"""


def inject_page_one_v3_css(html_text: str) -> str:
    """Template HTML の ``</style>`` 直前に CSS を inject する.

    既存の ``</style>`` がなければ ``</head>`` 直前に ``<style>...</style>``
    を新設する（v2 の inject_link_style_css と同じ作法）。
    """
    if "</style>" in html_text:
        idx = html_text.rfind("</style>")
        return html_text[:idx] + PAGE_ONE_V3_CSS + html_text[idx:]
    if "</head>" in html_text:
        head_close = html_text.find("</head>")
        injected = f"<style>\n{PAGE_ONE_V3_CSS}\n</style>\n"
        return html_text[:head_close] + injected + html_text[head_close:]
    return html_text
