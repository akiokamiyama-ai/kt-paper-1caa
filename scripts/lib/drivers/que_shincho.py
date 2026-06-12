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
1. ``sitemap.xml`` index → **全 sitemap page を fetch**（C76 で page 1 のみ
   走査の誤仮定を棄却。Drupal Simple XML Sitemap は **node ID 昇順で 2000
   件ずつ page 分割**するため、最新は最終 page に集中する。例：2026-06-10
   時点で page1 = ID 1-7669（古い）、page3 = 13955-18915（最新）。
   /int-foresight/ 等の最新国際記事を取りこぼさないため全 page を巡回し、
   lastmod 降順で合流させる）
2. ``/node/{id}/`` URL を ``lastmod`` 降順で N 件抽出
3. 各記事ページを fetch、JSON-LD NewsArticle を parse
4. **公開日 (datePublished) フィルタ**で「既存記事の編集」を排除
   sitemap.xml の lastmod は ``dateModified`` 同等なので、それだけで弁別不能。
   JSON-LD ``datePublished`` を弁別の根拠にする
5. **description 長さフィルタ**（80 字以上）で「title だけしか取れない」記事を排除
   contentAccess=premium でも og:description は出るため、長さ評価が実用的
6. **JSON-LD ``articleSection`` → Tribune category 動的マッピング**（C76 / C79）
   QUE は国内系（経済・社会・教育・医療・政治）→ business、国際系
   （Foresight / 国際）→ geopolitics、文化系 → books のハイブリッド媒体。
   ``raw["tribune_category"]`` 経由で page1 / page3 pipeline に伝播し、
   Article.to_pipeline_dict() で ``category`` フィールドに自動反映される。

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


# C76 (Sprint 9, 2026-06-10): QUE 記事の JSON-LD articleSection を Tribune の
# category 体系にマッピング。QUE は「NHK 的位置づけ + 旧 FORESIGHT 的位置づけ」
# のハイブリッド媒体で、国内系（経済・社会・教育・医療・政治）と国際系
# （Foresight・国際）が混在する。category=geopolitics 一律だと page3 R1 で
# Project Syndicate / War on the Rocks / Foreign Policy に常勝で負け、QUE は
# 5 日連続採用 0 件だった。本マッピングで国内系を business（page2 Today's
# Headlines / page3 R2）に、国際系を geopolitics（page3 R1/R3）に、文化系を
# books（page3 R5）に振り分ける。未知カテゴリは旧 FORESIGHT 後継として
# geopolitics を既定。
QUE_TRIBUNE_CATEGORY_MAP: dict[str, str] = {
    "経済・ビジネス":    "business",
    "社会":              "business",
    "教育":              "business",
    "医療・ウェルネス":  "business",
    "政治":              "business",
    "カルチャー":        "books",
    "ライフ":            "books",
    "テクノロジー":      "geopolitics",
    "国際":              "geopolitics",
    "Foresight":         "geopolitics",
}


def map_que_category_to_tribune(que_category: str | None) -> str:
    """QUE articleSection を Tribune category にマッピング。

    未知カテゴリ / 空文字 / None は ``geopolitics``（FORESIGHT 後継）を既定。
    """
    if not que_category:
        return "geopolitics"
    return QUE_TRIBUNE_CATEGORY_MAP.get(que_category.strip(), "geopolitics")

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

    category_que = (article.get("articleSection") or "").strip()
    # C76 (Sprint 9, 2026-06-10): JSON-LD articleSection から Tribune category
    # を動的決定。pipeline は raw["tribune_category"] を受けて記事個別の
    # category を優先する。未知カテゴリは geopolitics 既定（FORESIGHT 後継）。
    tribune_category = map_que_category_to_tribune(category_que)
    return Article(
        source_name=source.name,
        title=title,
        link=url,
        description=description,
        pub_date=pub_date,
        source_language=source.language,
        raw={
            "author": _author_name(article.get("author")),
            "category_que": category_que,
            "tribune_category": tribune_category,
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
                "  [que-scrape] no /node/ URLs discovered from sitemap",
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
        # C76 (Sprint 9, 2026-06-10): 旧仕様「先頭ページに最新エントリが集中」は
        # 誤った仮定だった。Drupal Simple XML Sitemap は **node ID 昇順** で
        # 2000 件ずつページ分割するため、最新記事は **最終ページ** に集中する。
        # 例：2026-06-10 時点で page1 = ID 1-7669（古い）、page3 = 13955-18915
        # （最新）。/int-foresight/ 記事（ID 18000 番台）が page1 走査では
        # 永遠に Stage 1 すら到達せず、5 日連続 QUE 採用 0 件の真因となっていた。
        # 全 page を走査して lastmod 降順に合流させることで、Drupal の page
        # 分割仕様（ID 順 / lastmod 順 / 件数閾値）が変わっても堅牢に動く。
        # HTTP request は 1 + N（N = sitemap page 数、現状 3）に増えるが、
        # 各 page は数百 KB の XML で軽量。
        all_candidates: list[tuple[str, str]] = []
        for page_url in pages:
            try:
                page_text = self._fetch_text(page_url)
            except Exception as e:  # noqa: BLE001
                print(
                    f"  [que-scrape] sitemap page FAIL ({page_url[:80]}): "
                    f"{type(e).__name__}: {e}",
                    file=sys.stderr,
                )
                continue
            all_candidates.extend(parse_sitemap_page(page_text))
        # lastmod 降順、ISO 8601 文字列の lex sort で時系列降順になる。
        # **前提**: Drupal Simple XML Sitemap が TZ 表記を統一して出す
        # （現状 ``+09:00`` 一律）。``Z`` と ``+09:00`` が混在すると lex sort
        # は時系列順と一致しなくなる（``Z`` < ``+`` の ASCII 順位差）。将来
        # 表記が混在し始めたら ``datetime.fromisoformat`` 比較に切替えること。
        all_candidates.sort(key=lambda x: x[1], reverse=True)
        return all_candidates[: self.top_n]
