"""Page I (Front Page) HTML rendering.

Builds the HTML for the Tribune's front-page section from a list of
translated article dicts and surgically replaces the existing
``<section class="page page-one">...</section>`` in the issue file.

Edits to the editorial copy (kicker labels, "なぜ重要か" sidebar, byline
formatting) live in :func:`build_page_one` so a future redesign can change
the markup in one place.
"""

from __future__ import annotations

import html


KICKERS = [
    "BBC ビジネス・トップ",
    "BBC ビジネス・産業",
    "BBC ビジネス・市場",
    "BBC ビジネス・金融",
]


def esc(s: str) -> str:
    return html.escape(s)


def render_top_body(top: dict) -> str:
    """Build the multi-paragraph body for the TOP article."""
    paragraphs: list[str] = []
    body = top.get("body_ja") or []
    if body:
        # First fetched paragraph as the dropcap-led lede.
        paragraphs.append(f'<p class="dropcap">{esc(body[0])}</p>')
        for p in body[1:]:
            paragraphs.append(f"<p>{esc(p)}</p>")
    else:
        paragraphs.append(f'<p class="dropcap">{esc(top["desc_ja"])}</p>')
    paragraphs.append(
        f'<p class="byline" style="margin-top:8px;">原題：<em>{esc(top["title"])}</em>　全文：'
        f'<a href="{esc(top["link"])}" target="_blank" rel="noopener noreferrer">BBC News</a></p>'
    )
    return "\n".join("          " + p for p in paragraphs)


def render_secondary_body(sec: dict) -> str:
    """Build the multi-paragraph body for a secondary article."""
    paragraphs: list[str] = []
    body = sec.get("body_ja") or []
    if body:
        for p in body:
            paragraphs.append(f"        <p>{esc(p)}</p>")
    else:
        paragraphs.append(f'        <p>{esc(sec["desc_ja"])}</p>')
    paragraphs.append(
        f'        <p class="byline" style="margin-top:6px;">原題：<em>{esc(sec["title"])}</em>　全文：'
        f'<a href="{esc(sec["link"])}" target="_blank" rel="noopener noreferrer">BBC News</a></p>'
    )
    return "\n".join(paragraphs)


def build_page_one(articles: list[dict]) -> str:
    top = articles[0]
    secs = articles[1:4]

    secondaries_html = []
    for i, s in enumerate(secs):
        kicker = KICKERS[i + 1]
        secondaries_html.append(
            f"""
      <div class="col" lang="ja">
        <div class="kicker">{esc(kicker)}</div>
        <h3 class="headline-l">{esc(s["title_ja"])}</h3>
        <p class="byline">本紙編集部　BBC News より構成</p>
{render_secondary_body(s)}
      </div>""".rstrip()
        )

    page = f"""<section class="page page-one">
    <div class="page-banner"><span class="pg-num">— Page I —</span> The Front Page · World &amp; Business</div>

    <article class="front-top">
      <div class="lead-story" lang="ja">
        <div class="kicker">{esc(KICKERS[0])}</div>
        <h2 class="headline-xl">{esc(top["title_ja"])}</h2>
        <p class="deck">{esc(top["desc_ja"])}</p>
        <p class="byline">本紙編集部　BBC News より構成</p>
        <div class="body-3col">
{render_top_body(top)}
        </div>
      </div>

      <aside class="lead-sidebar" lang="ja">
        <div class="kicker">なぜ重要か</div>
        <h4 class="headline-m">本日のトップから読み取るべきこと</h4>
        <p>BBC News が今朝発信したこのトップ記事を、本紙は本日の最初に頭に置くべき話題として第1面に据えた。読み解きのための3点：</p>
        <hr class="dotted" />
        <p><strong>1・</strong>記事の主題（『{esc(top["title_ja"])}』）が、グローバルな政治・経済の地形にどんな波紋を投げているかを把握する。</p>
        <p><strong>2・</strong>同じ事象を別の視点で扱うソース（FT・Economist・日経等）と読み比べ、フレーミングの違いを観察する。</p>
        <p><strong>3・</strong>このニュースが、今後1週間の意思決定タイムラインに何を加えるかを問う——それが本紙が翌朝以降に追跡すべき焦点となる。</p>
        <hr class="dotted" />
        <p class="byline" style="margin-top:8px;">出典：BBC News RSS · 翻訳：MyMemory</p>
      </aside>
    </article>

    <div class="secondaries">{"".join(secondaries_html)}
    </div>
  </section>"""

    return page


def replace_page_one(html_text: str, new_page_html: str) -> str:
    """Surgically replace the page-one section, preserving the rest verbatim."""
    start_marker = '<section class="page page-one">'
    if html_text.count(start_marker) != 1:
        raise RuntimeError(
            f"Expected 1 page-one section, found {html_text.count(start_marker)}"
        )
    start = html_text.find(start_marker)
    end = html_text.find("</section>", start)
    if end == -1:
        raise RuntimeError("Page One section end not found")
    end += len("</section>")
    return html_text[:start] + new_page_html + html_text[end:]
