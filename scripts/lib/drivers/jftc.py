"""公正取引委員会 (JFTC) — 報道発表 scraper (C120, Sprint 11, 2026-07-04).

公取委は RSS 未提供のため、月別 index ページ + 個別記事ページのシンプルな
2 段 fetch で実装。QueShinchoDriver と異なり sitemap / JSON-LD を扱わない
ため大幅に短い。

戦略
----
1. 当月 + 前月の ``/houdou/pressrelease/YYYY/{mon}/index.html`` を fetch
   （月替わり時の記事取りこぼしを防ぐ。当月のみだと 7/1 に前月分が消える）
2. 各 index で
   ``<a href="/houdou/pressrelease/YYYY/{mon}/YYMMDD_xxx.html">タイトル</a>``
   形式のリンクを parse
3. 上位 ``DEFAULT_TOP_N`` 件を選び、各記事ページから title / date / body を
   抽出
   - **title**: ``<h1>(令和X年M月D日)実際のタイトル</h1>`` の後半を採用
   - **date**: 令和 date から西暦に変換（令和 X = 2018 + X 年）
   - **body**: ``<div class="p_title">`` の後、``<h2>関連ファイル</h2>`` の
     前までの HTML から tag 除去 + 空白正規化

Brittleness
-----------
- HTML tag 位置が JFTC 側で変わると parse 失敗
- 月別 index の URL パターン（jul / jun / may 等の英略月）は Rails の
  ``strftime('%b')`` に相当、JFTC の慣習として長年安定
- 記事 fetch は 1 index あたり最大 top_n 件 + 前月分（同数）で HTTP 数は
  少ない。rate limit 心配不要
"""

from __future__ import annotations

import re
import sys
import urllib.error
import urllib.request
from datetime import date, datetime
from typing import Iterable
from zoneinfo import ZoneInfo

from ..source import Article, Source
from .base import DEFAULT_TIMEOUT
from .html import DEFAULT_ARTICLE_UA, HtmlScrapeDriver


# Public constants — tests reference these
HOST = "www.jftc.go.jp"
DEFAULT_TOP_N = 10

_JST = ZoneInfo("Asia/Tokyo")

_MONTH_EN_ABBREV: dict[int, str] = {
    1: "jan", 2: "feb", 3: "mar", 4: "apr", 5: "may", 6: "jun",
    7: "jul", 8: "aug", 9: "sep", 10: "oct", 11: "nov", 12: "dec",
}

# 令和 X 年 M 月 D 日 (title prefix) → 西暦 date
_REIWA_RE = re.compile(r"令和(\d+)年(\d+)月(\d+)日")

# index page の記事リンク:
#   /houdou/pressrelease/YYYY/{mon}/YYMMDD_xxx.html
# suffix は spc / kokuji / kketsu / kokoku 等が観測されるが、
# .html である事だけを制約に開く
_INDEX_LINK_RE = re.compile(
    r'<a\s+href="(/houdou/pressrelease/\d{4}/[a-z]{3}/[^"/]+\.html)"[^>]*>([^<]+)</a>',
    re.IGNORECASE,
)

# 本文抽出:
#   <div class="p_title" ...>...</div> 以降、<h2>関連ファイル</h2> の前まで
_ARTICLE_BODY_START_RE = re.compile(r'<div[^>]*class="p_title[^"]*"[^>]*>')
_ARTICLE_BODY_END_RE = re.compile(r"<h2[^>]*>\s*関連ファイル", re.IGNORECASE)

_H1_RE = re.compile(r"<h1[^>]*>(.+?)</h1>", re.DOTALL)


def _reiwa_to_gregorian(reiwa_year: int, month: int, day: int) -> date | None:
    """令和 X 年 = 2018 + X 年（令和 1 = 2019、令和 8 = 2026）."""
    if reiwa_year < 1:
        return None
    try:
        return date(2018 + reiwa_year, month, day)
    except ValueError:
        return None


def _http_get(url: str, *, timeout: int = DEFAULT_TIMEOUT) -> str | None:
    """1 URL fetch. UTF-8 で decode、失敗時は stderr に警告して None."""
    req = urllib.request.Request(
        url, headers={"User-Agent": DEFAULT_ARTICLE_UA},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        print(f"[jftc] fetch fail {url}: {e}", file=sys.stderr)
        return None


def _extract_body(html: str) -> str:
    """記事本文を抽出。<div class="p_title"> 以降、<h2>関連ファイル前まで."""
    start_m = _ARTICLE_BODY_START_RE.search(html)
    if not start_m:
        return ""
    start = start_m.end()
    end_m = _ARTICLE_BODY_END_RE.search(html, start)
    end = end_m.start() if end_m else min(start + 8000, len(html))
    body_html = html[start:end]
    body = re.sub(r"<[^>]+>", " ", body_html)
    body = (
        body.replace("&nbsp;", " ")
        .replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
    )
    body = re.sub(r"\s+", " ", body).strip()
    return body


def parse_article_page(html: str, url: str) -> dict | None:
    """個別記事 HTML から title / pub_date (date) / body を抽出.

    Public for tests. Returns dict or None if h1 not found.
    """
    h1_m = _H1_RE.search(html)
    if not h1_m:
        return None
    h1_text = re.sub(r"<[^>]+>", "", h1_m.group(1)).strip()
    date_m = _REIWA_RE.search(h1_text)
    pub_date: date | None = None
    title = h1_text
    if date_m:
        pub_date = _reiwa_to_gregorian(
            int(date_m.group(1)), int(date_m.group(2)), int(date_m.group(3)),
        )
        # title から (令和X年M月D日) prefix を削除
        title = re.sub(r"^\(令和\d+年\d+月\d+日\)\s*", "", h1_text).strip()
    body = _extract_body(html)
    return {
        "title": title,
        "pub_date": pub_date,
        "body": body,
        "link": url,
    }


def parse_index_links(html: str) -> list[tuple[str, str]]:
    """月別 index HTML から (relative_link, title) のリストを返す.

    Public for tests. 重複除去は caller 側。
    """
    out: list[tuple[str, str]] = []
    for m in _INDEX_LINK_RE.finditer(html):
        rel = m.group(1)
        title = m.group(2).strip()
        out.append((rel, title))
    return out


class JftcDriver(HtmlScrapeDriver):
    """Scrape ``https://www.jftc.go.jp/houdou/pressrelease/`` per-month index →
    per-article body.

    RSS 未提供のため月別 index の HTML を parse し、各記事詳細ページから
    title / date / body を抽出する。C120 初版。

    Parameters
    ----------
    top_n : int
        1 fetch あたりに返す最大記事件数。デフォルト ``DEFAULT_TOP_N`` = 10。
    """

    def __init__(self, *, site_config=None, top_n: int = DEFAULT_TOP_N):
        super().__init__(site_config=site_config)
        self.top_n = top_n

    def fetch(self, source: Source) -> Iterable[Article]:
        # 当月 + 前月の index URL 決定（JST 基準）
        today = datetime.now(_JST).date()
        year_months: list[tuple[int, int]] = [(today.year, today.month)]
        if today.month == 1:
            year_months.append((today.year - 1, 12))
        else:
            year_months.append((today.year, today.month - 1))

        seen_links: set[str] = set()
        candidates: list[tuple[str, str]] = []  # (absolute_link, index_title)
        for year, month in year_months:
            month_en = _MONTH_EN_ABBREV.get(month)
            if not month_en:
                continue
            index_url = (
                f"https://{HOST}/houdou/pressrelease/{year}/{month_en}/"
                f"index.html"
            )
            html = _http_get(index_url)
            if not html:
                continue
            for rel, title in parse_index_links(html):
                abs_url = f"https://{HOST}{rel}"
                if abs_url in seen_links:
                    continue
                seen_links.add(abs_url)
                candidates.append((abs_url, title))

        # index は最新順で並んでいる想定、上位 top_n 件を採用
        candidates = candidates[: self.top_n]

        articles: list[Article] = []
        for link, index_title in candidates:
            page_html = _http_get(link)
            if not page_html:
                continue
            parsed = parse_article_page(page_html, link)
            if not parsed:
                # fallback: index の title だけ利用（本文欠落）
                articles.append(Article(
                    source_name=source.name,
                    title=index_title,
                    link=link,
                    description="",
                    pub_date=None,
                    body_paragraphs=[],
                    source_language=source.language,
                ))
                continue

            pub_dt: datetime | None = None
            if parsed["pub_date"]:
                # JFTC 発表は原則 JST 業務日中、時刻不明のため 09:00 JST 仮定
                pub_dt = datetime.combine(
                    parsed["pub_date"], datetime.min.time(), tzinfo=_JST,
                ).replace(hour=9)

            body_text = parsed["body"] or ""
            articles.append(Article(
                source_name=source.name,
                title=parsed["title"] or index_title,
                link=link,
                description=body_text[:200],
                pub_date=pub_dt,
                body_paragraphs=[body_text] if body_text else [],
                source_language=source.language,
            ))
        return articles
