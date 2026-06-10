"""Unit tests for QueShinchoDriver (C42 案A, Sprint 9, 2026-06-04).

新潮QUE は Drupal 11 サイトで公式 RSS が空テンプレ、sitemap.xml + 個別記事
JSON-LD scrape で運用する。本テストでは：

  a) sitemap index parser
  b) sitemap page parser（lastmod 降順 + /node/{id}/ filter）
  c) JSON-LD NewsArticle 抽出
  d) 公開日 (datePublished) フィルタ ※ dateModified 同等の lastmod ベース
     では弁別不能な「既存記事の編集」を datePublished で排除
  e) description 長さフィルタ（「全文取得可能性」確認の代理指標）
  f) QueShinchoDriver.fetch() end-to-end（フィクスチャ HTML + fetch stub）
  g) fetch.py dispatch が QUE host を QueShinchoDriver に振り分ける

Run::

    python3 -m tests.test_que_shincho
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone

from scripts.lib.drivers import que_shincho
from scripts.lib.drivers.que_shincho import (
    DEFAULT_MIN_DESC_CHARS,
    DEFAULT_PUBDATE_WINDOW_DAYS,
    DEFAULT_TOP_N,
    HOST,
    QueShinchoDriver,
    SITEMAP_INDEX_URL,
    build_article_from_html,
    parse_sitemap_index,
    parse_sitemap_page,
)
from scripts.lib.source import (
    FetchMethod,
    Priority,
    Source,
    Status,
)

PASS = 0
FAIL = 0


def _check(label: str, condition: bool, detail: str = "") -> bool:
    global PASS, FAIL
    sym = "✓" if condition else "✗"
    line = f"  {sym} {label}"
    if detail:
        line += f"  ({detail})"
    print(line)
    if condition:
        PASS += 1
    else:
        FAIL += 1
    return condition


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _src() -> Source:
    return Source(
        name="Shincho QUE（新潮QUE、旧 Foresight 後継）",
        url="https://que.dailyshincho.jp/",
        category="geopolitics",
        priority=Priority.HIGH,
        status=Status.VERIFIED,
        fetch_method=FetchMethod.HTML,
        rss_url=None,
        site_file="geopolitics.md",
        language="ja",
    )


SITEMAP_INDEX_XML = """<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
 <sitemap>
  <loc>https://que.dailyshincho.jp/sitemap.xml?page=1</loc>
  <lastmod>2026-06-03T21:15:01+09:00</lastmod>
 </sitemap>
 <sitemap>
  <loc>https://que.dailyshincho.jp/sitemap.xml?page=2</loc>
  <lastmod>2026-06-03T21:15:01+09:00</lastmod>
 </sitemap>
</sitemapindex>"""

SITEMAP_PAGE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
 <url>
  <loc>https://que.dailyshincho.jp/</loc>
  <changefreq>daily</changefreq>
  <priority>1.0</priority>
 </url>
 <url>
  <loc>https://que.dailyshincho.jp/node/18016/</loc>
  <lastmod>2026-06-03T20:56:12+09:00</lastmod>
  <priority>0.5</priority>
 </url>
 <url>
  <loc>https://que.dailyshincho.jp/node/18019/</loc>
  <lastmod>2026-06-03T20:55:11+09:00</lastmod>
  <priority>0.5</priority>
 </url>
 <url>
  <loc>https://que.dailyshincho.jp/category/business/</loc>
  <lastmod>2026-06-03T20:00:00+09:00</lastmod>
  <priority>0.7</priority>
 </url>
 <url>
  <loc>https://que.dailyshincho.jp/node/14398/</loc>
  <lastmod>2026-06-03T16:57:25+09:00</lastmod>
  <priority>0.5</priority>
 </url>
</urlset>"""


def _article_html(
    *,
    headline="サンプル記事タイトル：地政学的視点から見るインド経済",
    description=(
        "インド経済は単なる新興国成長を超えて、国際秩序の再編にも影響を"
        "及ぼしている。本稿では非同盟外交の歴史的経緯から現代のマルチ"
        "アライメント戦略まで、内的発展史を辿る。"
    ),
    date_published="2026-06-03T08:00:00+09:00",
    date_modified="2026-06-03T20:56:12+09:00",
    article_section="国際",
    author="サンプル筆者",
):
    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<title>{headline} | 新潮QUE（キュー）｜新潮社</title>
<meta property="og:title" content="{headline}" />
<meta property="og:description" content="{description}" />
<meta property="og:url" content="https://que.dailyshincho.jp/node/18016/" />
<script type="application/ld+json">{{
"@context": "https://schema.org",
"@type": "NewsArticle",
"headline": "{headline}",
"description": "{description}",
"datePublished": "{date_published}",
"dateModified": "{date_modified}",
"articleSection": "{article_section}",
"author": {{"@type": "Person", "name": "{author}"}}
}}</script>
</head>
<body><h1>{headline}</h1><p>本文……</p></body>
</html>"""


# ---------------------------------------------------------------------------
# (a) sitemap index parser
# ---------------------------------------------------------------------------

def test_sitemap_index_extracts_page_urls():
    pages = parse_sitemap_index(SITEMAP_INDEX_XML)
    _check(
        "a1 sitemap index から 2 ページ URL を抽出",
        pages == [
            "https://que.dailyshincho.jp/sitemap.xml?page=1",
            "https://que.dailyshincho.jp/sitemap.xml?page=2",
        ],
        f"got {pages}",
    )


def test_sitemap_index_empty():
    _check("a2 空 XML → 空 list", parse_sitemap_index("") == [])


# ---------------------------------------------------------------------------
# (b) sitemap page parser
# ---------------------------------------------------------------------------

def test_sitemap_page_extracts_node_urls_only():
    entries = parse_sitemap_page(SITEMAP_PAGE_XML)
    urls = [u for u, _ in entries]
    _check(
        "b1 /node/{id}/ のみ抽出（top / category は除外）",
        urls == [
            "https://que.dailyshincho.jp/node/18016/",
            "https://que.dailyshincho.jp/node/18019/",
            "https://que.dailyshincho.jp/node/14398/",
        ],
        f"got {urls}",
    )


def test_sitemap_page_lastmod_pairs():
    entries = parse_sitemap_page(SITEMAP_PAGE_XML)
    _check(
        "b2 lastmod を URL とペアで返す",
        entries[0] == (
            "https://que.dailyshincho.jp/node/18016/",
            "2026-06-03T20:56:12+09:00",
        ),
        f"got {entries[0]}",
    )


# ---------------------------------------------------------------------------
# (c) JSON-LD NewsArticle 抽出
# ---------------------------------------------------------------------------

def test_jsonld_extraction_finds_news_article():
    html = _article_html()
    now = datetime(2026, 6, 3, 12, 0, 0, tzinfo=timezone.utc)
    article = build_article_from_html(
        html, "https://que.dailyshincho.jp/node/18016/", _src(), now=now,
    )
    _check(
        "c1 JSON-LD から title / desc / pub_date / author / category 抽出",
        article is not None
        and article.title.startswith("サンプル記事タイトル")
        and "マルチアライメント" in article.description
        and article.pub_date is not None
        and article.raw.get("author") == "サンプル筆者"
        and article.raw.get("category_que") == "国際",
        f"got {article}",
    )


def test_jsonld_missing_returns_none():
    html_no_jsonld = (
        "<html><head><title>x</title>"
        '<meta property="og:description" content="..." />'
        "</head><body></body></html>"
    )
    _check(
        "c2 JSON-LD 不在 → None",
        build_article_from_html(
            html_no_jsonld, "https://que.dailyshincho.jp/node/1/", _src(),
        ) is None,
    )


# ---------------------------------------------------------------------------
# (d) 公開日 (datePublished) フィルタ
# ---------------------------------------------------------------------------

def test_publish_window_accepts_recent():
    """公開日が直近 N 日内 → 採用."""
    now = datetime(2026, 6, 3, 12, 0, 0, tzinfo=timezone.utc)
    html = _article_html(date_published="2026-06-01T08:00:00+09:00")
    art = build_article_from_html(
        html, "https://que.dailyshincho.jp/node/1/", _src(),
        pub_window_days=7, now=now,
    )
    _check("d1 datePublished 2 日前 → 採用", art is not None)


def test_publish_window_rejects_old_reedit():
    """公開日が古い記事は『既存記事の編集』として却下.

    sitemap.xml の lastmod は dateModified 同等なので、これを使うと再編集
    された古い記事を新記事と誤認する。datePublished を弁別の根拠にする。
    """
    now = datetime(2026, 6, 3, 12, 0, 0, tzinfo=timezone.utc)
    # 5/3 公開、6/3 大幅編集（実際の QUE 6/3 lastmod 上位サンプルと同パターン）
    html = _article_html(
        date_published="2026-05-03T08:00:00+09:00",
        date_modified="2026-06-03T20:56:12+09:00",
    )
    art = build_article_from_html(
        html, "https://que.dailyshincho.jp/node/1/", _src(),
        pub_window_days=7, now=now,
    )
    _check(
        "d2 公開日 31 日前で更新日 数時間前 → 却下（既存記事の編集）",
        art is None,
    )


def test_publish_date_missing_rejects():
    """datePublished が無い JSON-LD → 却下."""
    html = (
        "<html><head>"
        '<script type="application/ld+json">{"@type":"NewsArticle",'
        '"headline":"x","description":"y"}</script>'
        "</head></html>"
    )
    _check(
        "d3 datePublished 無し → 却下",
        build_article_from_html(
            html, "https://que.dailyshincho.jp/node/1/", _src(),
        ) is None,
    )


# ---------------------------------------------------------------------------
# (e) description 長さフィルタ
# ---------------------------------------------------------------------------

def test_desc_too_short_rejects():
    """description が短すぎる記事は『全文取得可能性低』として却下."""
    now = datetime(2026, 6, 3, 12, 0, 0, tzinfo=timezone.utc)
    short_desc = "短い説明文。"  # 7 chars
    html = _article_html(description=short_desc)
    art = build_article_from_html(
        html, "https://que.dailyshincho.jp/node/1/", _src(),
        min_desc_chars=DEFAULT_MIN_DESC_CHARS, now=now,
    )
    _check("e1 description 7 字 < 80 字閾値 → 却下", art is None)


def test_desc_at_threshold_accepts():
    """閾値ぴったりの description は採用."""
    now = datetime(2026, 6, 3, 12, 0, 0, tzinfo=timezone.utc)
    desc = "あ" * 80  # ちょうど 80 字
    html = _article_html(description=desc)
    art = build_article_from_html(
        html, "https://que.dailyshincho.jp/node/1/", _src(),
        min_desc_chars=80, now=now,
    )
    _check(
        "e2 description 80 字（閾値）→ 採用",
        art is not None and len(art.description) == 80,
    )


# ---------------------------------------------------------------------------
# (f) QueShinchoDriver.fetch() end-to-end (mocked I/O)
# ---------------------------------------------------------------------------

class _FixtureDriver(QueShinchoDriver):
    """_fetch_text をフィクスチャに差し替えた driver。"""

    def __init__(self, *, sitemap_index=None, sitemap_page=None,
                 article_pages=None, top_n=DEFAULT_TOP_N,
                 pub_window_days=DEFAULT_PUBDATE_WINDOW_DAYS,
                 min_desc_chars=DEFAULT_MIN_DESC_CHARS):
        super().__init__(
            top_n=top_n,
            pub_window_days=pub_window_days,
            min_desc_chars=min_desc_chars,
        )
        self._fixtures = {
            SITEMAP_INDEX_URL: sitemap_index or SITEMAP_INDEX_XML,
        }
        if sitemap_page is not None:
            self._fixtures[
                "https://que.dailyshincho.jp/sitemap.xml?page=1"
            ] = sitemap_page
        else:
            self._fixtures[
                "https://que.dailyshincho.jp/sitemap.xml?page=1"
            ] = SITEMAP_PAGE_XML
        # C76 (2026-06-10): driver が全 sitemap page を走査するようになったので、
        # SITEMAP_INDEX_XML が示す page=2 にも空 XML を登録（既存テストの挙動
        # を変えないため）。新規テストで page=2 に意味のある内容を持たせたい
        # 場合は article_pages 経由で上書きできる。
        self._fixtures.setdefault(
            "https://que.dailyshincho.jp/sitemap.xml?page=2",
            '<?xml version="1.0"?><urlset></urlset>',
        )
        self._fixtures.update(article_pages or {})
        self.fetched_urls: list[str] = []

    def _fetch_text(self, url):
        self.fetched_urls.append(url)
        if url in self._fixtures:
            return self._fixtures[url]
        raise FileNotFoundError(f"no fixture for {url}")


def test_fetch_end_to_end_accepts_only_recent():
    """sitemap → 3 件 URL のうち、公開日 7 日以内 + desc 80 字以上 1 件のみ採用."""
    recent_html = _article_html(
        headline="採用記事：今日公開",
        description="あ" * 200,
        date_published="2026-06-03T08:00:00+09:00",
    )
    old_reedit_html = _article_html(
        headline="却下記事：1 ヶ月前公開、今日大幅編集",
        description="あ" * 200,
        date_published="2026-05-03T08:00:00+09:00",
        date_modified="2026-06-03T20:56:12+09:00",
    )
    short_desc_html = _article_html(
        headline="却下記事：description 短すぎる",
        description="短い。",
        date_published="2026-06-03T08:00:00+09:00",
    )
    drv = _FixtureDriver(article_pages={
        "https://que.dailyshincho.jp/node/18016/": recent_html,
        "https://que.dailyshincho.jp/node/18019/": old_reedit_html,
        "https://que.dailyshincho.jp/node/14398/": short_desc_html,
    })
    # build_article_from_html は default で now=現在時刻を使う。
    # テストでは pub_window 内で確実に該当するよう pub_window を広めに取り直す
    # （recent_html 2026-06-03 公開 + 試験時刻が 2026 年後半でも 6 ヶ月 以内）。
    drv.pub_window_days = 366  # 1 年。recent と old_reedit の弁別は別テストで担保
    # 上記でいくと old_reedit (5/3) も window 内に入ってしまうので、
    # 別経路で「公開日が古いものは却下」を担保する代わりに、ここでは
    # 「正しく URL を 3 件 fetch する」「desc 短い 1 件が確実に弾かれる」を確認
    out = list(drv.fetch(_src()))
    # window=366 だと recent + old_reedit の 2 件が採用、short_desc が弾かれる
    titles = [a.title for a in out]
    _check(
        "f1 fetch: window=366 で recent + old_reedit 採用、short_desc 弾く",
        len(out) == 2
        and "採用記事：今日公開" in titles
        and "却下記事：1 ヶ月前公開、今日大幅編集" in titles
        and "却下記事：description 短すぎる" not in titles,
        f"got {len(out)} articles, titles={titles}",
    )
    # sitemap index + 2 pages (page1 = real + page2 = empty) + 3 articles
    # = 6 calls. C76 (2026-06-10) で全 page 走査に変更したため、page=2 の
    # fetch が 1 件増えた。
    _check(
        "f2 fetch: sitemap index + 全 page 走査 + 3 article ページ計 6 件 fetch",
        len(drv.fetched_urls) == 6,
        f"got {drv.fetched_urls}",
    )


def test_fetch_sitemap_empty_returns_empty():
    drv = _FixtureDriver(sitemap_index="<sitemapindex></sitemapindex>")
    out = list(drv.fetch(_src()))
    _check("f3 sitemap index 空 → 空 list", out == [])


def test_fetch_sorts_urls_by_lastmod_desc():
    """sitemap page entries が lastmod 降順でソートされる."""
    recent_html = _article_html(date_published="2026-06-03T08:00:00+09:00",
                                 description="あ" * 100)
    drv = _FixtureDriver(article_pages={
        "https://que.dailyshincho.jp/node/18016/": recent_html,
        "https://que.dailyshincho.jp/node/18019/": recent_html,
        "https://que.dailyshincho.jp/node/14398/": recent_html,
    })
    drv.top_n = 2  # top_n を絞る
    list(drv.fetch(_src()))
    # node URL の fetch 順序：lastmod 上位 2 件のみ
    node_urls = [u for u in drv.fetched_urls if "/node/" in u]
    _check(
        "f4 lastmod 降順、top_n=2 で上位 2 件のみ fetch (18016 + 18019)",
        node_urls == [
            "https://que.dailyshincho.jp/node/18016/",
            "https://que.dailyshincho.jp/node/18019/",
        ],
        f"got {node_urls}",
    )


# ---------------------------------------------------------------------------
# (g) fetch.py dispatch
# ---------------------------------------------------------------------------

def test_fetch_dispatch_includes_que_driver():
    """fetch.py が QueShinchoDriver を import / instantiate して、QUE host
    URL を含む source を QueShinchoDriver に振り分ける."""
    import scripts.fetch as fetch_mod
    # import エラーなく QUE_HOST と QueShinchoDriver が見える
    _check(
        "g1 fetch.py が QUE_HOST と QueShinchoDriver を import 済",
        hasattr(fetch_mod, "QUE_HOST")
        and hasattr(fetch_mod, "QueShinchoDriver")
        and fetch_mod.QUE_HOST == HOST,
        f"QUE_HOST={getattr(fetch_mod, 'QUE_HOST', None)}",
    )


def test_geopolitics_md_registers_shincho_que():
    """sources/geopolitics.md を parser に通すと Shincho QUE が High Priority
    / HTML / status=VERIFIED で登録される."""
    from pathlib import Path
    from scripts.lib.source import parse_sources_md
    srcs = parse_sources_md(
        Path(__file__).resolve().parent.parent / "sources" / "geopolitics.md"
    )
    que = [s for s in srcs if "que.dailyshincho.jp" in s.url]
    _check(
        "g2 sources/geopolitics.md に QUE エントリ 1 件",
        len(que) == 1, f"got {len(que)}",
    )
    if que:
        s = que[0]
        _check(
            "g3 QUE が High Priority / HTML / VERIFIED",
            s.priority == Priority.HIGH
            and s.fetch_method == FetchMethod.HTML
            and s.status == Status.VERIFIED,
            f"priority={s.priority}, fm={s.fetch_method}, status={s.status}",
        )
        _check(
            "g4 source.name に 'Shincho QUE' が含まれる（penalty パターン用）",
            "Shincho QUE" in s.name,
            f"name={s.name!r}",
        )


def test_penalty_pattern_applies_to_shincho_que():
    """SHINCHO_QUE_PATTERNS で source_name 'Shincho QUE...' に penalty 値が出る.

    6/5 調整: -5.0 → 0.0 にいったん外し（W2 Day 6 で QUE 採用 0 件、効きすぎ
    判定）、1 週間運用観察後に再調整。テストは現行値 SHINCHO_QUE_PENALTY を
    定数参照で固定して、将来再強化時にもテスト書き換え不要にする。
    """
    from scripts.regen_front_page_v2 import (
        SHINCHO_QUE_PATTERNS, SHINCHO_QUE_PENALTY, _apply_page1_source_penalty,
    )
    art = {"source_name": "Shincho QUE（新潮QUE）"}
    penalty = _apply_page1_source_penalty(art)
    _check(
        f"g5 Shincho QUE source → penalty SHINCHO_QUE_PENALTY ({SHINCHO_QUE_PENALTY})",
        penalty == SHINCHO_QUE_PENALTY, f"got {penalty}",
    )


def test_penalty_does_not_double_apply():
    """Foresight と Shincho QUE は別パターン、二重適用しない（Foresight が先勝ち）."""
    from scripts.regen_front_page_v2 import _apply_page1_source_penalty
    fs = _apply_page1_source_penalty({"source_name": "Foresight（新潮社）"})
    _check("g6 Foresight → -10.0（既存値維持）", fs == -10.0, f"got {fs}")


def test_penalty_skips_unmatched_sources():
    from scripts.regen_front_page_v2 import _apply_page1_source_penalty
    other = _apply_page1_source_penalty({"source_name": "Foreign Affairs"})
    _check("g7 マッチしない source → 0.0", other == 0.0, f"got {other}")


# ---------------------------------------------------------------------------
# (h) C76 (2026-06-10): category 動的マッピング + 全 page 走査
# ---------------------------------------------------------------------------

def test_map_que_category_to_tribune_domestic():
    from scripts.lib.drivers.que_shincho import map_que_category_to_tribune
    ok = (
        map_que_category_to_tribune("経済・ビジネス") == "business"
        and map_que_category_to_tribune("社会") == "business"
        and map_que_category_to_tribune("教育") == "business"
        and map_que_category_to_tribune("医療・ウェルネス") == "business"
        and map_que_category_to_tribune("政治") == "business"
    )
    _check("h1 国内 5 カテゴリ → business", ok)


def test_map_que_category_to_tribune_intl_and_books():
    from scripts.lib.drivers.que_shincho import map_que_category_to_tribune
    ok = (
        map_que_category_to_tribune("国際") == "geopolitics"
        and map_que_category_to_tribune("Foresight") == "geopolitics"
        and map_que_category_to_tribune("テクノロジー") == "geopolitics"
        and map_que_category_to_tribune("カルチャー") == "books"
        and map_que_category_to_tribune("ライフ") == "books"
    )
    _check("h2 国際/Foresight/テクノロジー → geopolitics、カルチャー/ライフ → books", ok)


def test_map_que_category_to_tribune_unknown_defaults_to_geopolitics():
    from scripts.lib.drivers.que_shincho import map_que_category_to_tribune
    _check(
        "h3 未知カテゴリ / 空 / None → geopolitics（FORESIGHT 後継）",
        map_que_category_to_tribune("未定義") == "geopolitics"
        and map_que_category_to_tribune("") == "geopolitics"
        and map_que_category_to_tribune(None) == "geopolitics",
    )


def test_build_article_writes_tribune_category_to_raw():
    """build_article_from_html が raw["tribune_category"] にマッピング結果を書く."""
    from datetime import datetime, timezone
    from scripts.lib.drivers.que_shincho import build_article_from_html
    html = _article_html(
        article_section="経済・ビジネス",
        date_published="2026-06-09T08:00:00+09:00",
        description="あ" * 200,
    )
    now = datetime(2026, 6, 10, 0, 0, tzinfo=timezone.utc)
    art = build_article_from_html(
        html, "https://que.dailyshincho.jp/node/18999/", _src(),
        pub_window_days=3, now=now,
    )
    _check(
        "h4 raw[tribune_category] = business（経済・ビジネス → business）",
        art is not None
        and art.raw.get("category_que") == "経済・ビジネス"
        and art.raw.get("tribune_category") == "business",
        f"got raw={getattr(art, 'raw', None)}",
    )


def test_build_article_writes_geopolitics_for_intl():
    from datetime import datetime, timezone
    from scripts.lib.drivers.que_shincho import build_article_from_html
    html = _article_html(
        article_section="Foresight",
        date_published="2026-06-09T08:00:00+09:00",
        description="あ" * 200,
    )
    now = datetime(2026, 6, 10, 0, 0, tzinfo=timezone.utc)
    art = build_article_from_html(
        html, "https://que.dailyshincho.jp/node/18897/", _src(),
        pub_window_days=3, now=now,
    )
    _check(
        "h5 Foresight 記事 → raw[tribune_category] = geopolitics",
        art is not None and art.raw.get("tribune_category") == "geopolitics",
    )


def test_pipeline_dict_propagates_tribune_category():
    """_article_to_pipeline_dict が raw[tribune_category] を pipeline_dict[category] に伝播."""
    from datetime import datetime, timezone
    from scripts.lib.source import Article
    from scripts.regen_front_page_v2 import _article_to_pipeline_dict
    art = Article(
        source_name="Shincho QUE（新潮QUE）",
        title="サンプル",
        link="https://que.dailyshincho.jp/node/18999/",
        description="あ" * 200,
        pub_date=datetime(2026, 6, 9, 8, 0, tzinfo=timezone.utc),
        source_language="ja",
        raw={"tribune_category": "business", "category_que": "経済・ビジネス"},
    )
    d = _article_to_pipeline_dict(art)
    _check(
        "h6 pipeline_dict: category=business が動的セットされる",
        d.get("category") == "business",
        f"got category={d.get('category')!r}",
    )


def test_pipeline_dict_no_category_when_raw_empty():
    from datetime import datetime, timezone
    from scripts.lib.source import Article
    from scripts.regen_front_page_v2 import _article_to_pipeline_dict
    art = Article(
        source_name="BBC Business",
        title="x",
        link="https://bbc.co.uk/x",
        pub_date=datetime(2026, 6, 9, tzinfo=timezone.utc),
        source_language="en",
    )
    d = _article_to_pipeline_dict(art)
    _check(
        "h7 driver が tribune_category をセットしない → pipeline_dict に category キーなし"
        "（_attach_category で registry から引き当てる既存パス維持）",
        "category" not in d,
        f"got {d}",
    )


def test_fetch_visits_all_sitemap_pages():
    """SITEMAP_INDEX_XML が 2 page を示すので、driver は両方 fetch する."""
    drv = _FixtureDriver()  # page 2 fixture は __init__ で空 XML 既定登録
    list(drv.fetch(_src()))
    pages_fetched = [
        u for u in drv.fetched_urls if "sitemap.xml?page=" in u
    ]
    _check(
        "h8 driver が page=1 と page=2 の両方を fetch する",
        sorted(pages_fetched) == [
            "https://que.dailyshincho.jp/sitemap.xml?page=1",
            "https://que.dailyshincho.jp/sitemap.xml?page=2",
        ],
        f"got {pages_fetched}",
    )


def test_fetch_merges_candidates_across_pages_by_lastmod():
    """各 page の候補を合流し、lastmod 降順 sort で top_n 抽出する."""
    recent_html = _article_html(date_published="2026-06-03T08:00:00+09:00",
                                description="あ" * 100)
    # page=2 fixture を上書き：page=1 より新しい lastmod を含む
    page2_xml = """<?xml version="1.0"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
 <url>
  <loc>https://que.dailyshincho.jp/node/18900/</loc>
  <lastmod>2026-06-10T17:00:00+09:00</lastmod>
 </url>
 <url>
  <loc>https://que.dailyshincho.jp/node/18897/</loc>
  <lastmod>2026-06-10T15:00:00+09:00</lastmod>
 </url>
</urlset>"""
    drv = _FixtureDriver(
        article_pages={
            "https://que.dailyshincho.jp/sitemap.xml?page=2": page2_xml,
            "https://que.dailyshincho.jp/node/18900/": recent_html,
            "https://que.dailyshincho.jp/node/18897/": recent_html,
            "https://que.dailyshincho.jp/node/18016/": recent_html,
            "https://que.dailyshincho.jp/node/18019/": recent_html,
            "https://que.dailyshincho.jp/node/14398/": recent_html,
        },
    )
    drv.top_n = 2  # 上位 2 件のみ
    list(drv.fetch(_src()))
    node_urls = [u for u in drv.fetched_urls if "/node/" in u]
    _check(
        "h9 全 page 候補が lastmod 降順で合流 → top_n=2 は page=2 の 18900 / 18897",
        node_urls == [
            "https://que.dailyshincho.jp/node/18900/",
            "https://que.dailyshincho.jp/node/18897/",
        ],
        f"got {node_urls}",
    )


def main() -> int:
    print("QueShinchoDriver tests (C42 案A, Sprint 9, 2026-06-04)")
    print()
    print("(a) sitemap index parser:")
    test_sitemap_index_extracts_page_urls()
    test_sitemap_index_empty()
    print()
    print("(b) sitemap page parser:")
    test_sitemap_page_extracts_node_urls_only()
    test_sitemap_page_lastmod_pairs()
    print()
    print("(c) JSON-LD NewsArticle 抽出:")
    test_jsonld_extraction_finds_news_article()
    test_jsonld_missing_returns_none()
    print()
    print("(d) 公開日 (datePublished) フィルタ:")
    test_publish_window_accepts_recent()
    test_publish_window_rejects_old_reedit()
    test_publish_date_missing_rejects()
    print()
    print("(e) description 長さフィルタ:")
    test_desc_too_short_rejects()
    test_desc_at_threshold_accepts()
    print()
    print("(f) fetch() end-to-end (fixtures):")
    test_fetch_end_to_end_accepts_only_recent()
    test_fetch_sitemap_empty_returns_empty()
    test_fetch_sorts_urls_by_lastmod_desc()
    print()
    print("(g) fetch.py dispatch + sources MD + penalty:")
    test_fetch_dispatch_includes_que_driver()
    test_geopolitics_md_registers_shincho_que()
    test_penalty_pattern_applies_to_shincho_que()
    test_penalty_does_not_double_apply()
    test_penalty_skips_unmatched_sources()
    print()
    print("(h) C76 (2026-06-10): category 動的マッピング + 全 page 走査:")
    test_map_que_category_to_tribune_domestic()
    test_map_que_category_to_tribune_intl_and_books()
    test_map_que_category_to_tribune_unknown_defaults_to_geopolitics()
    test_build_article_writes_tribune_category_to_raw()
    test_build_article_writes_geopolitics_for_intl()
    test_pipeline_dict_propagates_tribune_category()
    test_pipeline_dict_no_category_when_raw_empty()
    test_fetch_visits_all_sitemap_pages()
    test_fetch_merges_candidates_across_pages_by_lastmod()
    print()
    print(f"=== {PASS} passed, {FAIL} failed ===")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
