"""HTML scraping drivers.

This module ships two things:

* :class:`HtmlScrapeDriver` — a stub feed-style driver for sites whose
  ``Source.fetch_method`` is ``HTML``. Today it just emits a single
  placeholder Article so the orchestrator can show "scraping not yet
  implemented" entries in reports without crashing. Per-site subclasses
  (e.g. for the Shopify-based 山と道 store, the SaaS YAMAP マガジン, or
  the WordPress-but-no-RSS 好書好日) plug in here.

* :class:`BbcArticleScraper` — a body-paragraph extractor for BBC News
  article pages. Used by the regen_front_page pipeline to pull the lede +
  3-4 supporting paragraphs out of an item the RSS driver only gave us a
  one-line description for. Ported verbatim from
  ``experiment/regen_front_page.py:fetch_article_paragraphs``; the
  brittleness (regex-against-CSS-class-name) is documented in
  ``roadmap.md`` §4.2.
"""

from __future__ import annotations

import html
import re
import sys
import urllib.error
import urllib.request
from typing import Iterable

from ..source import Article, Source
from .base import DEFAULT_TIMEOUT, SourceDriver, check_url_scheme


class HtmlScrapeDriver(SourceDriver):
    """Placeholder for sources whose RSS is gone or never existed.

    Subclasses override :meth:`fetch` for site-specific scraping (e.g.
    Shopify storefronts, SaaS magazines). The base implementation emits one
    diagnostic Article so the orchestrator can list these sources in its
    report without dropping them silently.
    """

    def fetch(self, source: Source) -> Iterable[Article]:
        return [
            Article(
                source_name=source.name,
                title=f"[scraper not implemented] {source.name}",
                link=source.url,
                description=(
                    "RSS unavailable. Add a per-site HtmlScrapeDriver subclass "
                    "to populate articles for this source."
                ),
            )
        ]


# ---------------------------------------------------------------------------
# BBC News article body extractor
# ---------------------------------------------------------------------------

_BBC_PARA_RE = re.compile(
    r'<p[^>]*class="[^"]*sc-[^"]*"[^>]*>(.*?)</p>', re.DOTALL
)
_TAG_STRIP_RE = re.compile(r"<[^>]+>")
_WS_COLLAPSE_RE = re.compile(r"\s+")

PARA_MIN_LEN = 60
PARA_MAX_LEN = 480
DEFAULT_ARTICLE_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) kt-tribune/0.6"
)


class BbcArticleScraper:
    """Pull the first N body paragraphs out of a BBC News article page.

    BBC styles body paragraphs with a styled-component class ``sc-XXXX``;
    we match that and strip the HTML inside. Any change to BBC's front-end
    framework breaks this — see ``roadmap.md`` §4.2 (known brittleness).
    """

    def __init__(self, user_agent: str = DEFAULT_ARTICLE_UA, timeout: int = DEFAULT_TIMEOUT) -> None:
        self.user_agent = user_agent
        self.timeout = timeout

    def paragraphs(self, url: str, max_n: int) -> list[str]:
        try:
            check_url_scheme(url)
        except ValueError as e:
            print(f"  [bbc-scrape] REJECT: {e}", file=sys.stderr)
            return []
        try:
            req = urllib.request.Request(url, headers={"User-Agent": self.user_agent})
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                page = resp.read().decode("utf-8", errors="replace")
        except (urllib.error.URLError, TimeoutError) as e:
            print(f"  [bbc-scrape] FAIL {url[:60]}: {e}", file=sys.stderr)
            return []
        out: list[str] = []
        for raw in _BBC_PARA_RE.findall(page):
            text = _TAG_STRIP_RE.sub("", raw)
            text = _WS_COLLAPSE_RE.sub(" ", text).strip()
            text = html.unescape(text)
            if len(text) < PARA_MIN_LEN:
                continue
            if len(text) > PARA_MAX_LEN:
                text = text[:PARA_MAX_LEN].rsplit(" ", 1)[0] + "…"
            out.append(text)
            if len(out) >= max_n:
                break
        return out
