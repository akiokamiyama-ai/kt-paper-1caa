"""個人情報保護委員会 (PPC) — 報道発表 scraper.

C142 (Sprint 12, 2026-07-13) 実装。こころみ（介護・傾聴事業）における
個人情報保護は顧客対話・コンプライアンス直結の一次ソース。C120 で追加した
「個人情報保護委員会」source (companies.md #8 個人情報保護委員会) が
[scraper not implemented] placeholder になっていた事象への対処。

戦略
----
1. 報道発表資料一覧ページを 1 回 fetch
   (``https://www.ppc.go.jp/news/press/``)
2. HTML の ``<ul class="news-list">`` から
   ``<time datetime="YYYY-MM-DD">日付</time><div class="news-text"><a>title</a>``
   のペアを抽出
3. 上位 ``DEFAULT_TOP_N`` 件を Article として返す（C140 と同型で
   ``MAX_AGE_DAYS=90`` の日付足切りを適用）

JFA driver とほぼ同型（1 HTTP / list-only / 個別記事非 fetch）:
- 一覧ページの ``<time datetime="...">`` から ISO 日付が直接取れる
  （JFA は ``YYYY.MM.DD`` の別 regex parse が必要だったが、PPC はより単純）
- 個別記事 fetch は不要。title / date / URL で Stage 1/2 評価に十分
- 1 fetch/日 で完結、rate limit 心配ゼロ

Robots.txt
----------
- Disallow: ``/common/*``, ``/hardcore/*``, ``/hc_config/``, ``/image/``,
  ``/webadmin/*``
- ``/news/`` および ``/news/press/`` は制限なし → Allow
- ``kt-tribune/0.6`` UA での fetch は許可範囲内

URL の注意
----------
PPC の HTML 内に ``/news/press/2026/26 622`` のような**スペース付き相対 URL**
が観測される（サーバ側の生成漏れ、302 redirect で解決）。driver 側で
``urllib.parse.quote`` により空白を URL エンコードする。
"""

from __future__ import annotations

import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta
from typing import Iterable
from zoneinfo import ZoneInfo

from ..source import Article, Source
from .base import DEFAULT_TIMEOUT
from .html import DEFAULT_ARTICLE_UA, HtmlScrapeDriver


# Public constants — tests reference these
HOST = "www.ppc.go.jp"
LIST_URL = f"https://{HOST}/news/press/"
DEFAULT_TOP_N = 10

# C142 (Sprint 12, 2026-07-13): C140 と同一の 90 日窓を採用。PPC 報道発表は
# 年度単位でタブ分けされており、当年度タブに直近の 3-10 件が並ぶ運用。
# 更新頻度は月 1-3 本程度で JFA よりやや高いが同程度の cadence として扱う。
# pub_date が None の記事は permissive に通す（driver parse 失敗時の防御）。
DEFAULT_MAX_AGE_DAYS = 90

_JST = ZoneInfo("Asia/Tokyo")

# 一覧の 1 エントリ:
#   <time datetime=" YYYY-MM-DD " class="news-date">令和X年M月D日</time>
#   <div class="news-text"><a href="URL">TITLE</a></div>
# datetime 属性は前後に空白が入る可能性あり (\s* 許容)、URL は絶対 / 相対
# 両方の可能性、title は改行や連続空白が入りうる。
_ENTRY_RE = re.compile(
    r'<time\s+datetime="\s*(\d{4}-\d{2}-\d{2})\s*"[^>]*class="news-date"[^>]*>'
    r'[^<]+</time>\s*'
    r'<div class="news-text">\s*<a\s+href="([^"]+)"[^>]*>([^<]+)</a>',
    re.DOTALL,
)

_ISO_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")


def _http_get(url: str, *, timeout: int = DEFAULT_TIMEOUT) -> str | None:
    """1 URL fetch. UTF-8 decode、失敗時 stderr 警告 + None."""
    req = urllib.request.Request(
        url, headers={"User-Agent": DEFAULT_ARTICLE_UA},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        print(f"[ppc] fetch fail {url}: {e}", file=sys.stderr)
        return None


def _parse_iso_date(s: str) -> date | None:
    """YYYY-MM-DD 形式 → date."""
    m = _ISO_DATE_RE.match(s.strip())
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def _normalize_url(raw: str) -> str | None:
    """相対 URL → 絶対 URL 補完 + パス部の空白 URL エンコード.

    C142: PPC の HTML には ``/news/press/2026/26 622`` のような空白を含む
    相対 URL が観測される（サーバ側の HTML 生成漏れ、302 redirect で
    最終的には正しい URL へ解決される）。driver 側で ``urllib.parse.quote``
    で空白のみ encode する（他の特殊文字は既存の encode を保持）。
    """
    raw = raw.strip()
    if not raw:
        return None
    # 相対 URL → 絶対 URL
    if raw.startswith("/"):
        raw = f"https://{HOST}{raw}"
    elif not raw.startswith("http"):
        return None
    # パス部のみ空白を encode（クエリ / fragment は保持）
    parsed = urllib.parse.urlsplit(raw)
    encoded_path = urllib.parse.quote(parsed.path, safe="/")
    return urllib.parse.urlunsplit((
        parsed.scheme, parsed.netloc, encoded_path,
        parsed.query, parsed.fragment,
    ))


def parse_list_page(html: str) -> list[dict]:
    """一覧ページの HTML から (date, url, title) の辞書リストを返す.

    Public for tests. entries は登場順（最新順に並んでいる想定、当年度
    タブが最上位に表示される）。
    """
    entries: list[dict] = []
    for m in _ENTRY_RE.finditer(html):
        d = _parse_iso_date(m.group(1))
        url = _normalize_url(m.group(2))
        if not url:
            continue
        title = re.sub(r"\s+", " ", m.group(3)).strip()
        entries.append({"date": d, "url": url, "title": title})
    return entries


class PpcDriver(HtmlScrapeDriver):
    """Scrape ``https://www.ppc.go.jp/news/press/`` press release list.

    一覧ページ 1 回 fetch で完結（JFA driver と同型）。個別記事ページは
    叩かない（本文の title / date は一覧で取得可能、Stage 1/2 評価に十分）。

    C142 (Sprint 12, 2026-07-13) 初版。C140 と同型の MAX_AGE_DAYS=90 で
    press release の日付足切りを行う。
    """

    def __init__(
        self, *, site_config=None, top_n: int = DEFAULT_TOP_N,
        max_age_days: int | None = DEFAULT_MAX_AGE_DAYS,
    ):
        """
        Parameters
        ----------
        max_age_days :
            C142 press release 型 driver の日付足切り。None または 0 以下で
            無効化。デフォルト 90 日（JFA / JFTC と統一）。
        """
        super().__init__(site_config=site_config)
        self.top_n = top_n
        self.max_age_days = max_age_days

    def fetch(self, source: Source) -> Iterable[Article]:
        html = _http_get(LIST_URL)
        if not html:
            return []
        entries = parse_list_page(html)
        entries = entries[: self.top_n]

        # C142: MAX_AGE_DAYS 日付足切り。JFA / JFTC と同一設計。
        cutoff_date: date | None = None
        if self.max_age_days and self.max_age_days > 0:
            cutoff_date = datetime.now(_JST).date() - timedelta(
                days=self.max_age_days,
            )

        articles: list[Article] = []
        skipped_old = 0
        for e in entries:
            title = e["title"]
            url = e["url"]
            d = e["date"]
            if cutoff_date and d is not None and d < cutoff_date:
                skipped_old += 1
                continue
            # PPC 発表は JST の業務日、09:00 JST 仮想時刻
            pub_dt: datetime | None = None
            if d:
                pub_dt = datetime.combine(
                    d, datetime.min.time(), tzinfo=_JST,
                ).replace(hour=9)
            # description は title 再利用（個別記事本文を叩かない設計）。
            # Stage 1 の description 30 字フィルタを通すため prefix を付ける。
            description = f"個人情報保護委員会報道発表: {title}"
            articles.append(Article(
                source_name=source.name,
                title=title,
                link=url,
                description=description,
                pub_date=pub_dt,
                body_paragraphs=[description],
                source_language=source.language,
            ))
        if skipped_old:
            print(
                f"[ppc] max_age_days={self.max_age_days}: skipped {skipped_old} "
                f"articles older than {cutoff_date}",
                file=sys.stderr,
            )
        return articles
