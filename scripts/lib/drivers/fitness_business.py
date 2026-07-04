"""Fitness Business (business.fitnessclub.jp) — sitemap + JSON-LD scraper.

C122 (Sprint 11, 2026-07-04) 実装。Web-Repo 事業ドメイン「フィットネス」
カバーのため、RSS 未提供の Fitness Business を sitemap.xml + 個別記事の
JSON-LD 経由で scrape する。

戦略
----
1. ``sitemap.xml`` を fetch し、``/articles/-/{ID}`` の URL を lastmod
   降順で N 件抽出
2. 各記事ページを fetch し、JSON-LD の Article schema から
   ``datePublished`` / ``description``、meta description から冒頭抜粋を
   抽出
3. Fitness Business は会員制の有料 wall があり本文全文は取れないが、
   冒頭 100-200 字（meta description）は取れる。Tribune の Stage 1/2
   評価には十分（BBC の description truncate と同じ扱い）

Robots.txt
----------
- ``User-agent: Googlebot-News`` の Disallow は ``/search/`` /
  ``/category/seminar/`` / ``/category/tour/`` / ``/category/data/`` のみ
- ``/articles/-/*`` と ``sitemap.xml`` は明示的に許可
- 公式に Sitemap URL を robots.txt で提供している = クローラを歓迎

Brittleness
-----------
- sitemap の URL 数は 2400+ で、fetch 対象は上位 top_n 件のみに絞る
- 各記事 fetch は最大 top_n 回（default=10）
- JSON-LD が壊れた場合は meta description のみで fallback
"""

from __future__ import annotations

import json
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime
from typing import Iterable
from zoneinfo import ZoneInfo

from ..source import Article, Source
from .base import DEFAULT_TIMEOUT
from .html import DEFAULT_ARTICLE_UA, HtmlScrapeDriver


# Public constants (tests reference)
HOST = "business.fitnessclub.jp"
SITEMAP_URL = f"https://{HOST}/sitemap.xml"
DEFAULT_TOP_N = 10

_JST = ZoneInfo("Asia/Tokyo")

# sitemap: <url><loc>URL</loc>[<lastmod>DATE</lastmod>]?</url>
# 実サイトの sitemap は lastmod を持たない（C122 実装時に確認）ため、
# lastmod 部分は optional。並び順は lastmod > article ID 降順で決める。
_SITEMAP_URL_RE = re.compile(
    r"<url>\s*<loc>([^<]+)</loc>\s*(?:<lastmod>([^<]+)</lastmod>\s*)?</url>",
    re.IGNORECASE | re.DOTALL,
)
_ARTICLE_URL_PAT = re.compile(r"^https://[^/]+/articles/-/(\d+)/?$")

# 個別記事: JSON-LD 内の Article schema
_JSON_LD_RE = re.compile(
    r'<script[^>]*type="application/ld\+json"[^>]*>(.+?)</script>',
    re.DOTALL,
)

_META_DESC_RE = re.compile(
    r'<meta\s+(?:name|property)="(?:og:)?description"[^>]*content="([^"]+)"',
    re.IGNORECASE,
)


def _http_get(url: str, *, timeout: int = DEFAULT_TIMEOUT) -> str | None:
    """1 URL fetch. UTF-8 で decode、失敗時 stderr 警告 + None."""
    req = urllib.request.Request(
        url, headers={"User-Agent": DEFAULT_ARTICLE_UA},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        print(f"[fitness_business] fetch fail {url}: {e}", file=sys.stderr)
        return None


def parse_sitemap_articles(xml_text: str) -> list[tuple[str, str]]:
    """sitemap.xml から (article_url, lastmod) を lastmod 降順で返す.

    Public for tests. Filter は ``/articles/-/{ID}`` パターンにマッチする
    URL のみ。lastmod があれば ISO 8601 の文字列比較で降順、無い場合は
    article ID (URL 末尾の数字) の降順 fallback（記事 ID は原則昇順に
    採番される想定、新しい記事ほど ID が大きい）。
    """
    entries: list[tuple[str, str, int]] = []  # (url, lastmod, id_int)
    for m in _SITEMAP_URL_RE.finditer(xml_text):
        url = (m.group(1) or "").strip()
        lastmod = (m.group(2) or "").strip()
        id_match = _ARTICLE_URL_PAT.match(url)
        if not id_match:
            continue
        try:
            id_int = int(id_match.group(1))
        except ValueError:
            id_int = 0
        entries.append((url, lastmod, id_int))
    # lastmod があるものと無いものが混在する場合、lastmod 降順を優先し、
    # 無いものは ID 降順（同じ key スケールで比較できるよう空 lastmod は
    # 常に劣後、ID 大きいほど新しい）。
    entries.sort(key=lambda t: (t[1], t[2]), reverse=True)
    return [(url, lastmod) for url, lastmod, _ in entries]


def _pick_article_json_ld(html: str) -> dict | None:
    """JSON-LD script tag から Article / NewsArticle schema を 1 つ選ぶ."""
    for m in _JSON_LD_RE.finditer(html):
        text = m.group(1).strip()
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            continue
        # list or dict
        candidates: list[dict] = data if isinstance(data, list) else [data]
        for c in candidates:
            if not isinstance(c, dict):
                continue
            t = c.get("@type")
            if t == "Article" or t == "NewsArticle" or (
                isinstance(t, list) and any(x in ("Article", "NewsArticle") for x in t)
            ):
                return c
    return None


def parse_article_page(html: str, url: str) -> dict | None:
    """個別記事から title / pub_dt / body 抽出.

    Public for tests. JSON-LD Article schema が主源、meta description が
    body 冒頭の fallback。h1 は補助的にタイトル特定に使う。
    """
    ld = _pick_article_json_ld(html)
    # title の 3 候補: JSON-LD headline > h1 > <title>
    title = ""
    if ld:
        headline = ld.get("headline") or ld.get("name")
        if isinstance(headline, str):
            title = headline.strip()
    if not title:
        # h1 (空でない最初の 1 つ)
        for m in re.finditer(r"<h1[^>]*>(.+?)</h1>", html, re.DOTALL):
            t = re.sub(r"<[^>]+>", "", m.group(1)).strip()
            if t:
                title = t
                break
    if not title:
        m = re.search(r"<title[^>]*>([^<]+)</title>", html)
        if m:
            title = m.group(1).strip()
            # "タイトル | Fitness Business" → 前半
            title = re.sub(r"\s*\|\s*Fitness Business\s*$", "", title)

    if not title:
        return None

    # date: JSON-LD datePublished を優先
    pub_dt: datetime | None = None
    if ld:
        raw = ld.get("datePublished") or ld.get("dateModified")
        if isinstance(raw, str):
            try:
                pub_dt = datetime.fromisoformat(raw)
            except ValueError:
                pass

    # body: JSON-LD description > meta description
    body = ""
    if ld:
        desc = ld.get("description")
        if isinstance(desc, str):
            body = desc.strip()
    if not body:
        m = _META_DESC_RE.search(html)
        if m:
            body = m.group(1).strip()
    # &hellip; / &nbsp; などの HTML entity を軽く正規化
    body = (
        body.replace("&nbsp;", " ").replace("&amp;", "&")
        .replace("&hellip;", "…").replace("&#8230;", "…")
        .replace("&quot;", '"')
    )

    return {
        "title": title,
        "pub_dt": pub_dt,
        "body": body,
        "link": url,
    }


class FitnessBusinessDriver(HtmlScrapeDriver):
    """Fitness Business (business.fitnessclub.jp) sitemap → JSON-LD scraper.

    C122 (Sprint 11, 2026-07-04) 初版。Web-Repo フィットネス系事業領域の
    カバーが目的。会員制 wall のため本文全文は取れないが、meta
    description で冒頭 100-200 字が取得可能で Stage 1/2 評価には十分。
    """

    def __init__(self, *, site_config=None, top_n: int = DEFAULT_TOP_N):
        super().__init__(site_config=site_config)
        self.top_n = top_n

    def fetch(self, source: Source) -> Iterable[Article]:
        sitemap_html = _http_get(SITEMAP_URL)
        if not sitemap_html:
            return []
        entries = parse_sitemap_articles(sitemap_html)
        # 上位 top_n 件（lastmod 降順で並んでいる）
        entries = entries[: self.top_n]

        articles: list[Article] = []
        for url, _lastmod in entries:
            page_html = _http_get(url)
            if not page_html:
                continue
            parsed = parse_article_page(page_html, url)
            if not parsed:
                continue

            body_text = parsed["body"] or ""
            articles.append(Article(
                source_name=source.name,
                title=parsed["title"],
                link=url,
                description=body_text[:250],
                pub_date=parsed["pub_dt"],
                body_paragraphs=[body_text] if body_text else [],
                source_language=source.language,
            ))
        return articles
