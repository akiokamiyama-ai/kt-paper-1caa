"""新潮QUE (Shincho QUE) — Drupal site without working RSS.

C42 案A (Sprint 9, 2026-06-04) 実装。新潮社 FORESIGHT が 5/18 に新潮QUE
へ統合された結果、旧 FORESIGHT RSS は新規記事 0 件で在庫枯渇が迫り、
新潮QUE 側の公式 RSS は空テンプレ（``rss.xml`` で ``<item>`` 0 件）。

調査 (6/4) で次のことを確認：
- ``https://que.dailyshincho.jp/rss.xml`` は依然として 200 / 355 bytes / 空
- ``https://que.dailyshincho.jp/sitemap.xml`` は **daily 更新中**
  （Drupal Simple XML Sitemap モジュール、本日付 lastmod 多数）
- 個別記事ページに **JSON-LD NewsArticle** + GTM ``dataLayer`` が出ており、
  ``datePublished`` / ``dateModified`` / ``articleSection`` / author /
  description が機械的に取れる

戦略
----
1. ``sitemap.xml`` index → 最新 sitemap page だけ fetch（先頭ページに最新が集中）
2. ``/node/{id}/`` URL を ``lastmod`` 降順で N 件抽出
3. 各記事ページを fetch、JSON-LD NewsArticle を parse
4. **公開日 (datePublished) フィルタ**で「既存記事の編集」を排除
   sitemap.xml の lastmod は ``dateModified`` 同等なので、それだけで弁別不能。
   JSON-LD ``datePublished`` を弁別の根拠にする
5. **description 長さフィルタ**（80 字以上）で「title だけしか取れない」記事を排除
   contentAccess=premium でも og:description は出るため、長さ評価が実用的

Brittleness 注意
----------------
- Drupal フロント変更で JSON-LD のタグ命名が変わる可能性
- フィクスチャテストで主要 path をカバー、5/19 BBC scraper と同様の脆さ
- 早期検知用に sitemap が空・記事 0 件・JSON-LD 欠落を stderr に記録
"""

from __future__ import annotations

import json
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Iterable

from ..source import Article, Source
from .base import DEFAULT_TIMEOUT
from .html import DEFAULT_ARTICLE_UA, HtmlScrapeDriver


# Public API constants — テストからも参照する
HOST = "que.dailyshincho.jp"
SITEMAP_INDEX_URL = f"https://{HOST}/sitemap.xml"
DEFAULT_TOP_N = 25
DEFAULT_PUBDATE_WINDOW_DAYS = 7
DEFAULT_MIN_DESC_CHARS = 80

# Regex patterns
_SITEMAP_INDEX_LOC_RE = re.compile(
    r'<sitemap>\s*<loc>([^<]+)</loc>', re.DOTALL,
)
_URL_BLOCK_RE = re.compile(
    r'<url>\s*<loc>([^<]+)</loc>\s*<lastmod>([^<]+)</lastmod>', re.DOTALL,
)
_NODE_URL_RE = re.compile(r'/node/\d+/?$')
_JSONLD_RE = re.compile(
    r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>',
    re.DOTALL,
)


def _parse_iso_date(s: str | None) -> datetime | None:
    """Parse '2026-06-03T08:00:00+09:00' style timestamps to UTC datetime."""
    if not s or not isinstance(s, str):
        return None
    s = s.strip().replace("Z", "+00:00")
    try:
        d = datetime.fromisoformat(s)
    except (ValueError, TypeError):
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc)


def _extract_news_article_jsonld(html_text: str) -> dict | None:
    """Return the first JSON-LD object whose @type is NewsArticle, or None."""
    for m in _JSONLD_RE.finditer(html_text):
        raw = m.group(1).strip()
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        # Some pages put a list at the root; handle both.
        candidates = data if isinstance(data, list) else [data]
        for d in candidates:
            if isinstance(d, dict) and d.get("@type") == "NewsArticle":
                return d
    return None


def _author_name(author_field) -> str:
    if isinstance(author_field, dict):
        return (author_field.get("name") or "").strip()
    if isinstance(author_field, list) and author_field:
        first = author_field[0]
        if isinstance(first, dict):
            return (first.get("name") or "").strip()
    if isinstance(author_field, str):
        return author_field.strip()
    return ""


def parse_sitemap_index(text: str) -> list[str]:
    """Return list of sitemap page URLs found in the index."""
    return [m.strip() for m in _SITEMAP_INDEX_LOC_RE.findall(text)]


def parse_sitemap_page(text: str) -> list[tuple[str, str]]:
    """Return list of (url, lastmod_iso) from a sitemap page.

    Only entries matching /node/{id}/ are returned (filters out category /
    series / static pages from the sitemap).
    """
    out: list[tuple[str, str]] = []
    for m in _URL_BLOCK_RE.finditer(text):
        u = m.group(1).strip()
        lastmod = m.group(2).strip()
        if _NODE_URL_RE.search(u):
            out.append((u, lastmod))
    return out


def build_article_from_html(
    html_text: str,
    url: str,
    source: Source,
    *,
    pub_window_days: int = DEFAULT_PUBDATE_WINDOW_DAYS,
    min_desc_chars: int = DEFAULT_MIN_DESC_CHARS,
    now: datetime | None = None,
) -> Article | None:
    """Parse one QUE article HTML page into an Article, or None to reject.

    Rejection reasons:
    - No JSON-LD NewsArticle present
    - datePublished missing or older than `pub_window_days`
      (so re-edited old articles are skipped — sitemap lastmod alone can't
      distinguish a re-edit from a new publish)
    - description shorter than `min_desc_chars` (extraction quality filter)
    """
    article = _extract_news_article_jsonld(html_text)
    if article is None:
        return None

    pub_date = _parse_iso_date(article.get("datePublished"))
    if pub_date is None:
        return None

    if now is None:
        now = datetime.now(timezone.utc)
    age = now - pub_date
    if age > timedelta(days=pub_window_days):
        return None  # 既存記事の編集など、公開日が古い記事

    description = (article.get("description") or "").strip()
    if len(description) < min_desc_chars:
        return None

    title = (article.get("headline") or article.get("name") or "").strip()
    if not title:
        return None

    return Article(
        source_name=source.name,
        title=title,
        link=url,
        description=description,
        pub_date=pub_date,
        source_language=source.language,
        raw={
            "author": _author_name(article.get("author")),
            "category_que": (article.get("articleSection") or "").strip(),
            "datePublished": article.get("datePublished") or "",
            "dateModified": article.get("dateModified") or "",
        },
    )


class QueShinchoDriver(HtmlScrapeDriver):
    """Sitemap-driven scraper for 新潮QUE (que.dailyshincho.jp).

    Subclass of :class:`HtmlScrapeDriver` so the fetch.py dispatch loop can
    route only QUE hosts here while everything else stays on the placeholder.

    Parameters
    ----------
    user_agent :
        HTTP User-Agent for HTML / sitemap fetches.
    top_n :
        Maximum number of /node/{id}/ pages to fetch per ``fetch()`` call.
    pub_window_days :
        Articles whose ``datePublished`` is older than this many days are
        skipped (suppresses re-edits of legacy archive content).
    min_desc_chars :
        Articles whose JSON-LD description is shorter than this are skipped.
    timeout :
        HTTP timeout in seconds.
    """

    def __init__(
        self,
        *,
        user_agent: str = DEFAULT_ARTICLE_UA,
        top_n: int = DEFAULT_TOP_N,
        pub_window_days: int = DEFAULT_PUBDATE_WINDOW_DAYS,
        min_desc_chars: int = DEFAULT_MIN_DESC_CHARS,
        timeout: int = DEFAULT_TIMEOUT,
        site_config=None,
    ) -> None:
        super().__init__(site_config=site_config)
        self.user_agent = user_agent
        self.top_n = top_n
        self.pub_window_days = pub_window_days
        self.min_desc_chars = min_desc_chars
        self.timeout = timeout

    # ------------------------------------------------------------------
    # I/O hooks — overridable for tests / fixtures
    # ------------------------------------------------------------------

    def _fetch_text(self, url: str) -> str:
        req = urllib.request.Request(
            url, headers={"User-Agent": self.user_agent},
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")

    # ------------------------------------------------------------------
    # Public driver API
    # ------------------------------------------------------------------

    def fetch(self, source: Source) -> Iterable[Article]:
        urls = self._discover_recent_urls()
        if not urls:
            print(
                f"  [que-scrape] no /node/ URLs discovered from sitemap",
                file=sys.stderr,
            )
            return []

        accepted: list[Article] = []
        for url, _lastmod in urls:
            try:
                html_text = self._fetch_text(url)
            except (urllib.error.URLError, TimeoutError) as e:
                print(f"  [que-scrape] FAIL {url[:60]}: {e}", file=sys.stderr)
                continue
            except Exception as e:  # noqa: BLE001
                print(
                    f"  [que-scrape] FAIL {url[:60]}: "
                    f"{type(e).__name__}: {e}",
                    file=sys.stderr,
                )
                continue
            art = build_article_from_html(
                html_text, url, source,
                pub_window_days=self.pub_window_days,
                min_desc_chars=self.min_desc_chars,
            )
            if art is not None:
                accepted.append(art)
        print(
            f"  [que-scrape] discovered {len(urls)} URL(s), "
            f"accepted {len(accepted)} new article(s)",
            file=sys.stderr,
        )
        return accepted

    def _discover_recent_urls(self) -> list[tuple[str, str]]:
        try:
            index_text = self._fetch_text(SITEMAP_INDEX_URL)
        except Exception as e:  # noqa: BLE001
            print(
                f"  [que-scrape] sitemap index FAIL: "
                f"{type(e).__name__}: {e}",
                file=sys.stderr,
            )
            return []
        pages = parse_sitemap_index(index_text)
        if not pages:
            return []
        # 先頭ページに最新エントリが集中している（経験的）。安全のため最初の 1 ページ
        # のみ fetch して network 負荷を抑える。
        first_page = pages[0]
        try:
            page_text = self._fetch_text(first_page)
        except Exception as e:  # noqa: BLE001
            print(
                f"  [que-scrape] sitemap page FAIL: "
                f"{type(e).__name__}: {e}",
                file=sys.stderr,
            )
            return []
        candidates = parse_sitemap_page(page_text)
        # lastmod 降順、ISO 8601 文字列の lex sort で時系列降順になる
        candidates.sort(key=lambda x: x[1], reverse=True)
        return candidates[: self.top_n]
