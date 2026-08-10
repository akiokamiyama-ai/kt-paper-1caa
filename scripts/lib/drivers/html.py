"""HTML scraping drivers.

This module ships two things:

* :class:`HtmlScrapeDriver` — a stub feed-style driver for sites whose
  ``Source.fetch_method`` is ``HTML``. Today it just emits a single
  placeholder Article so the orchestrator can show "scraping not yet
  implemented" entries in reports without crashing. Per-site subclasses
  (e.g. for the Shopify-based 山と道 store, the SaaS YAMAP マガジン, or
  the WordPress-but-no-RSS 好書好日) plug in here.

* :class:`BbcArticleScraper` — **DEPRECATED / 現在機能していない**。
  BBC News 記事ページの本文段落抽出。詳細は同クラスの docstring を参照。
"""

from __future__ import annotations

import html
import re
import sys
import urllib.error
import urllib.request
import warnings
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
                source_language=source.language,
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

    .. deprecated:: C156 (Sprint 13, 2026-08-10)

        **2026-08 時点で BBC の CSS 変更により本文抽出が機能しない。**
        **C155 で Today's Headlines を廃止したことに伴い実質未使用。**

    経緯:
        BBC は本文段落を styled-component の class ``sc-XXXX`` で描画しており、
        本クラスはそれを正規表現でマッチして中の HTML を剥がしていた。この
        「CSS クラス名への正規表現マッチ」という作りの脆さは ``roadmap.md``
        §4.2 と ``scripts/SUMMARY.md`` §12 で当初から既知の負債として記録
        されており、「BBC が sc- prefix を変えた場合：silently 0件返却」と
        failure mode まで予見されていた。

        C155a (2026-08-10) のコスト調査でそれが実際に起きていたことが判明した。
        Today's Headlines の LLM 要約は BBC 記事限定で本文を取りに行く設計
        だったが、``page2.headlines_summary`` タグの呼び出しが 8/1-8/10 の
        10 日間で **0 件**。実 URL で確認したところ段落抽出が 0 件を返しており、
        ``BODY_MIN_CHARS`` 未満 → description の truncate に fallback していた。
        結果、紙面には RSS の英語 description が翻訳も要約もされずに出ていた。

        この「英語のまま出る」事象は 2026-06-29 に神山さんが観察していたが
        (C109)、当時は真因が「BBC の Page I 採用 → Today's Headlines 降格」
        （降格先に翻訳経路が無い）と結論づけられた。実際には**真因は 2 つ**
        あり、もう一方が本 scraper の破損だった。詳細は
        ``docs/observations.md``「2 面 Headlines 英語ソースの和訳消失」節。

    現在の状態:
        C155 で ``scripts/selector/todays_headlines.py`` ごと廃止されたため、
        本番 cron 経路 (``regen_front_page_v3`` → ``regen_front_page_v2``)
        からは呼ばれない。唯一の import 元は Phase 1 のレガシー
        ``scripts/regen_front_page.py``（``archive/2026-04-25.html`` を
        書き換える使い捨てスクリプトで、cron / GHA からは実行されない）。

    直すなら:
        CSS クラス名依存をやめ、``<article>`` / ``<main>`` 配下の ``<p>`` を
        拾う構造ベースの抽出か、Readability 系ライブラリの導入が必要。
        BBC 以外にも効かせたいなら後者。C155 で新設した
        ``scripts/page5/article_summarizer.py`` は本クラスに依存せず、
        description だけでも要約できる二段構えにしてある。
    """

    def __init__(self, user_agent: str = DEFAULT_ARTICLE_UA, timeout: int = DEFAULT_TIMEOUT) -> None:
        self.user_agent = user_agent
        self.timeout = timeout

    def paragraphs(self, url: str, max_n: int) -> list[str]:
        """本文段落を最大 ``max_n`` 本返す。**現在は常に空リストを返す。**

        C156: 抽出 0 件のとき、従来は黙って ``[]`` を返していた。呼び出し側は
        「本文が短い記事」と区別できず fallback に落ちるだけなので、破損が
        10 日以上気づかれなかった（C155a）。0 件は「そういう記事」ではなく
        **セレクタ破損のシグナル**なので、明示的に warn を出す。
        """
        warnings.warn(
            "BbcArticleScraper は 2026-08 時点で BBC の CSS 変更により機能して "
            "いません（C156）。本メソッドは常に空リストを返します。",
            DeprecationWarning,
            stacklevel=2,
        )
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
        matches = _BBC_PARA_RE.findall(page)
        out: list[str] = []
        for raw in matches:
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

        # C156: 0 件の原因を「セレクタが当たらない」と「当たったが全部短い」に
        # 切り分けて出す。前者が破損のシグナル（2026-08 時点はこちら）。
        if not out:
            if not matches:
                print(
                    f"  [bbc-scrape] BROKEN: sc- prefix セレクタが 1 件も当たらない "
                    f"({len(page)} bytes) — BBC の CSS 変更による既知の破損 (C156). "
                    f"{url[:60]}",
                    file=sys.stderr,
                )
            else:
                print(
                    f"  [bbc-scrape] EMPTY: {len(matches)} 段落マッチしたが全て "
                    f"{PARA_MIN_LEN} 字未満 — 記事側が短い可能性. {url[:60]}",
                    file=sys.stderr,
                )
        return out
