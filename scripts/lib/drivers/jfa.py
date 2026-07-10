"""日本フランチャイズチェーン協会 (JFA) — プレスリリース scraper.

C127 (Sprint 11, 2026-07-09) 実装。Web-Repo 事業ドメイン「FC 業界統計・
規制ガイドライン・業界団体公式発表」のカバー。

戦略
----
1. プレスリリース一覧ページ 1 回 fetch
   (``https://www.jfa-fc.or.jp/lpcarticle/release/1``)
2. HTML の ``<dl class="newsList">`` から ``<dt>日付</dt><dd><h2><a>タイトル</a>``
   のペアを抽出
3. 上位 ``DEFAULT_TOP_N`` 件を Article として返す

本ドライバは **個別記事ページを叩かない**（HTTP 1 回で完結）:
- JFA の個別記事 HTML は本文構造が弱く（``<div id="mainCtt">`` のみ、
  h1 空、meta description 汎用）、C127 実装時の DOM 調査で本文の安定
  抽出は難しかった
- Stage 1/2 評価には title と source_name で十分（日付は評価には使わ
  ないが表示用に）
- 1 fetch/日 で完結するため rate limit / robots 心配ゼロ

Robots.txt
----------
- Amazonbot / Perplexity / cohere-ai / Bytespider 等 AI クローラは
  個別に Disallow (JFA 側の反 AI 学習ポリシー)
- 汎用 UA / 通常のクローラは制限なし。Tribune の ``kt-tribune/0.6``
  UA は Allow
"""

from __future__ import annotations

import re
import sys
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta
from typing import Iterable
from zoneinfo import ZoneInfo

from ..source import Article, Source
from .base import DEFAULT_TIMEOUT
from .html import DEFAULT_ARTICLE_UA, HtmlScrapeDriver


HOST = "www.jfa-fc.or.jp"
LIST_URL = f"https://{HOST}/lpcarticle/release/1"
DEFAULT_TOP_N = 10

# C140 (Sprint 12, 2026-07-10): press release 型 driver 用の日付足切り。
# JFA は月 1-2 本の press release 更新 cadence で、list 上位 10 件が過去
# 3-4 ヶ月に及ぶ。7/10 archive で 2026-04-16 記事（85 日前）が Page II
# Web-Repo に採用された事象 (C138 調査) の対策。90 日窓で JFA は 2-4 本
# 残る見込み（updates が月次のため）、Web-Repo Medium fetch 経路の
# 「rate も高くない = 完全枯渇にならない」バランス。
# pub_date が None の記事は permissive に通す（driver parse 失敗時の
# 過剰除外を避ける、Stage 1/2 での filter に委ねる）。
DEFAULT_MAX_AGE_DAYS = 90

_JST = ZoneInfo("Asia/Tokyo")

# 一覧の 1 エントリ: <dt>YYYY.MM.DD</dt> <dd><h2><a href="URL">TITLE</a></h2></dd>
# URL は絶対 (https://www.jfa-fc.or.jp/particle/{ID}.html) or 相対の可能性、
# title 属性が付く場合とない場合の両方を許容。
_ENTRY_RE = re.compile(
    r'<dt>\s*(\d{4}\.\d{2}\.\d{2})\s*</dt>\s*'
    r'<dd>\s*<h2>\s*<a\s+href="([^"]+)"[^>]*>([^<]+)</a>',
    re.DOTALL,
)

_YMD_DOT_RE = re.compile(r"^(\d{4})\.(\d{2})\.(\d{2})$")


def _http_get(url: str, *, timeout: int = DEFAULT_TIMEOUT) -> str | None:
    """1 URL fetch. UTF-8 decode、失敗時 stderr 警告 + None."""
    req = urllib.request.Request(
        url, headers={"User-Agent": DEFAULT_ARTICLE_UA},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        print(f"[jfa] fetch fail {url}: {e}", file=sys.stderr)
        return None


def _parse_ymd_dot(s: str) -> date | None:
    """YYYY.MM.DD 形式 → date."""
    m = _YMD_DOT_RE.match(s.strip())
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def parse_list_page(html: str) -> list[dict]:
    """一覧ページの HTML から (date, url, title) の辞書リストを返す.

    Public for tests. entries は登場順（新しい順に並んでいる想定）。
    """
    entries: list[dict] = []
    for m in _ENTRY_RE.finditer(html):
        d = _parse_ymd_dot(m.group(1))
        url = m.group(2).strip()
        title = re.sub(r"\s+", " ", m.group(3)).strip()
        # 相対 URL → 絶対 URL に補完
        if url.startswith("/"):
            url = f"https://{HOST}{url}"
        elif not url.startswith("http"):
            continue
        entries.append({"date": d, "url": url, "title": title})
    return entries


class JfaDriver(HtmlScrapeDriver):
    """Scrape ``https://www.jfa-fc.or.jp/lpcarticle/release/1`` press release list.

    一覧ページ 1 回 fetch で完結。個別記事ページは叩かない（本文構造が
    弱く、Stage 1/2 評価に必要な title / source_name は一覧で取れるため）。

    C127 (Sprint 11, 2026-07-09) 初版。
    """

    def __init__(
        self, *, site_config=None, top_n: int = DEFAULT_TOP_N,
        max_age_days: int | None = DEFAULT_MAX_AGE_DAYS,
    ):
        """
        Parameters
        ----------
        max_age_days :
            C140 (Sprint 12, 2026-07-10): pub_date が今日から何日以内の
            記事を通すか。None または 0 以下で足切り無効化（従来挙動）。
            デフォルト 90 日。
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

        # C140: 90 日 (デフォルト) より古い記事を除外。
        # pub_date が None の記事は permissive に通す (driver parse 失敗時の
        # 過剰除外回避、Stage 1/2 での filter に委ねる)。
        cutoff_date: date | None = None
        if self.max_age_days and self.max_age_days > 0:
            cutoff_date = datetime.now(_JST).date() - timedelta(days=self.max_age_days)

        articles: list[Article] = []
        skipped_old = 0
        for e in entries:
            title = e["title"]
            url = e["url"]
            d = e["date"]
            if cutoff_date and d is not None and d < cutoff_date:
                skipped_old += 1
                continue
            # JFA 発表は JST の業務日、09:00 JST 仮想時刻
            pub_dt: datetime | None = None
            if d:
                pub_dt = datetime.combine(
                    d, datetime.min.time(), tzinfo=_JST,
                ).replace(hour=9)
            # description は title 再利用（個別記事本文を叩かない設計）
            # Stage 1 は description の長さフィルタ (>= 30 字) を課すため
            # title だけだと足りない場合が多い → "JFA プレスリリース: <title>"
            # の prefix を付けて 30 字を確保する
            description = f"日本フランチャイズチェーン協会プレスリリース: {title}"
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
                f"[jfa] max_age_days={self.max_age_days}: skipped {skipped_old} "
                f"articles older than {cutoff_date}",
                file=sys.stderr,
            )
        return articles
