"""Unit tests for scripts.lib.drivers.ppc (C142, 2026-07-13).

固定 HTML fixture でパース関数と MAX_AGE_DAYS フィルタの挙動を検証。
ネットワーク不要。

Run::

    python3 -m tests.test_ppc
"""

from __future__ import annotations

from datetime import date, timedelta

from scripts.lib.drivers import ppc as P

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
# (a) _parse_iso_date
# ---------------------------------------------------------------------------

def test_parse_iso_date_basic():
    _check("a1 2026-07-07 → date(2026,7,7)",
           P._parse_iso_date("2026-07-07") == date(2026, 7, 7))


def test_parse_iso_date_with_whitespace():
    _check("a2 前後の空白は許容",
           P._parse_iso_date("  2026-07-07  ") == date(2026, 7, 7))


def test_parse_iso_date_invalid_format():
    _check("a3 不正フォーマット (YYYY.MM.DD) → None",
           P._parse_iso_date("2026.07.07") is None)


def test_parse_iso_date_out_of_range():
    _check("a4 存在しない日 (2026-13-01) → None",
           P._parse_iso_date("2026-13-01") is None)


# ---------------------------------------------------------------------------
# (b) _normalize_url
# ---------------------------------------------------------------------------

def test_normalize_url_absolute():
    _check("b1 絶対 URL はそのまま",
           P._normalize_url("https://www.ppc.go.jp/news/press/x/") ==
           "https://www.ppc.go.jp/news/press/x/")


def test_normalize_url_relative_to_absolute():
    _check("b2 相対 URL → 絶対 URL 補完",
           P._normalize_url("/news/press/x/") ==
           "https://www.ppc.go.jp/news/press/x/")


def test_normalize_url_encodes_space():
    """PPC HTML の生成漏れで空白を含む URL の対応."""
    _check("b3 空白を含む相対 URL は URL エンコードされる",
           P._normalize_url("/news/press/2026/26 622") ==
           "https://www.ppc.go.jp/news/press/2026/26%20622")


def test_normalize_url_empty():
    _check("b4 空文字列 → None", P._normalize_url("") is None)


def test_normalize_url_non_http():
    _check("b5 http(s) 以外の scheme (mailto: 等) → None",
           P._normalize_url("mailto:foo@example.com") is None)


# ---------------------------------------------------------------------------
# (c) parse_list_page
# ---------------------------------------------------------------------------

_SAMPLE_LIST = """
<div class="item-main js-tab-content">
<ul class="news-list">
<li>
<time datetime=" 2026-07-07 " class="news-date">令和8年7月7日</time>
<div class="news-text"><a href="/news/press/2026/260707">個人情報保護委員会　令和７年度年次報告の公表について</a></div>
</li>
<li>
<time datetime=" 2026-06-22 " class="news-date">令和8年6月22日</time>
<div class="news-text"><a href="/news/press/2026/26 622">令和８年度「個人情報を考える週間」について</a></div>
</li>
<li>
<time datetime=" 2026-06-01 " class="news-date">令和8年6月1日</time>
<div class="news-text"><a href="https://www.ppc.go.jp/news/press/2026/260601">「個人情報に関するポスターコンクール」を開催します</a></div>
</li>
</ul>
</div>
"""


def test_parse_list_returns_3_entries():
    entries = P.parse_list_page(_SAMPLE_LIST)
    _check("c1 3 エントリ抽出", len(entries) == 3, f"got {len(entries)}")


def test_parse_list_first_entry():
    e = P.parse_list_page(_SAMPLE_LIST)[0]
    _check("c2 date", e["date"] == date(2026, 7, 7))
    _check("c3 url (相対 → 絶対)",
           e["url"] == "https://www.ppc.go.jp/news/press/2026/260707")
    _check("c4 title", "令和７年度年次報告" in e["title"])


def test_parse_list_space_url_encoded():
    e = P.parse_list_page(_SAMPLE_LIST)[1]
    _check("c5 空白付き URL は %20 エンコード",
           e["url"] == "https://www.ppc.go.jp/news/press/2026/26%20622",
           f"got {e['url']}")


def test_parse_list_absolute_url_preserved():
    e = P.parse_list_page(_SAMPLE_LIST)[2]
    _check("c6 絶対 URL は保持",
           e["url"] == "https://www.ppc.go.jp/news/press/2026/260601")


def test_parse_list_empty_html():
    _check("c7 空 HTML → 空リスト", P.parse_list_page("") == [])


def test_parse_list_no_news_list_returns_empty():
    _check("c8 news-list 構造なし → 空リスト",
           P.parse_list_page("<html><body>no list</body></html>") == [])


# ---------------------------------------------------------------------------
# (d) 定数 sanity
# ---------------------------------------------------------------------------

def test_host_constant():
    _check("d1 HOST", P.HOST == "www.ppc.go.jp")


def test_list_url_constant():
    _check("d2 LIST_URL は /news/press/ を指す",
           "/news/press/" in P.LIST_URL)


def test_max_age_days_constant():
    _check("d3 DEFAULT_MAX_AGE_DAYS = 90 (JFA/JFTC と統一)",
           P.DEFAULT_MAX_AGE_DAYS == 90)


# ---------------------------------------------------------------------------
# (e) C142: MAX_AGE_DAYS 日付足切り
# ---------------------------------------------------------------------------

def _make_source():
    from scripts.lib.source import Source, Priority, Status, FetchMethod
    return Source(
        name="PPC", url=f"https://{P.HOST}/news/",
        category="companies:Cocolomi",
        priority=Priority.REFERENCE, status=Status.PARTIAL,
        fetch_method=FetchMethod.HTML, site_file="companies.md",
    )


def test_driver_default_max_age():
    d = P.PpcDriver()
    _check("e1 driver default max_age_days = 90", d.max_age_days == 90)


def test_driver_disabled_max_age():
    d = P.PpcDriver(max_age_days=None)
    _check("e2 max_age_days=None で足切り無効", d.max_age_days is None)


def test_fetch_filters_old_articles():
    """C142: 90 日超の記事は除外、90 日以内は通る."""
    from datetime import datetime as _dt
    ref_today = date(2026, 7, 13)
    ok_date = ref_today - timedelta(days=89)
    old_date = ref_today - timedelta(days=91)
    html = f"""
<ul class="news-list">
<li>
<time datetime=" {ok_date.isoformat()} " class="news-date">JP</time>
<div class="news-text"><a href="/news/press/new/">新しい</a></div>
</li>
<li>
<time datetime=" {old_date.isoformat()} " class="news-date">JP</time>
<div class="news-text"><a href="/news/press/old/">古い</a></div>
</li>
</ul>
"""
    orig_http = P._http_get
    orig_dt = P.datetime
    P._http_get = lambda url, timeout=None: html

    class _FakeDatetime(_dt):
        @classmethod
        def now(cls, tz=None):
            return _dt.combine(ref_today, _dt.min.time(), tzinfo=tz)
    P.datetime = _FakeDatetime
    try:
        articles = list(P.PpcDriver().fetch(_make_source()))
    finally:
        P._http_get = orig_http
        P.datetime = orig_dt
    _check("e3 89 日前は通る、91 日前は除外",
           len(articles) == 1 and articles[0].link.endswith("/news/press/new/"),
           f"got urls={[a.link for a in articles]}")


def test_fetch_pub_date_none_permissive():
    """C142: pub_date=None (parse 失敗) は permissive に通す."""
    html = """
<ul class="news-list">
<li>
<time datetime=" 2026-13-01 " class="news-date">JP</time>
<div class="news-text"><a href="/news/press/x/">日付不明</a></div>
</li>
</ul>
"""
    orig_http = P._http_get
    P._http_get = lambda url, timeout=None: html
    try:
        articles = list(P.PpcDriver().fetch(_make_source()))
    finally:
        P._http_get = orig_http
    _check("e4 pub_date=None (parse 失敗) は permissive に通す",
           len(articles) == 1 and articles[0].pub_date is None,
           f"got {len(articles)} articles, pub_date={articles[0].pub_date if articles else 'N/A'}")


def test_fetch_disabled_max_age_passes_old():
    """C142: max_age_days=None で 100 日前記事も通る."""
    from datetime import datetime as _dt
    ref_today = date(2026, 7, 13)
    old_date = ref_today - timedelta(days=100)
    html = f"""
<ul class="news-list">
<li>
<time datetime=" {old_date.isoformat()} " class="news-date">JP</time>
<div class="news-text"><a href="/news/press/old/">古い</a></div>
</li>
</ul>
"""
    orig_http = P._http_get
    orig_dt = P.datetime
    P._http_get = lambda url, timeout=None: html

    class _FakeDatetime(_dt):
        @classmethod
        def now(cls, tz=None):
            return _dt.combine(ref_today, _dt.min.time(), tzinfo=tz)
    P.datetime = _FakeDatetime
    try:
        articles = list(P.PpcDriver(max_age_days=None).fetch(_make_source()))
    finally:
        P._http_get = orig_http
        P.datetime = orig_dt
    _check("e5 max_age_days=None で 100 日前記事も通る",
           len(articles) == 1)


def test_fetch_description_prefix_added():
    """C142: description に「個人情報保護委員会報道発表: 」prefix が付く.

    実際の PPC 発表タイトルは長いため Stage 1 の 30 字フィルタは通るが、
    ここでは prefix が確実に付与されることのみ検証（title 由来の長さは
    別問題）。実データでは
    「個人情報保護委員会報道発表: 個人情報保護委員会 令和７年度年次...」
    のような 40+ 字になる。
    """
    real_title = "個人情報保護委員会 令和７年度年次報告の公表について（令和８年７月７日）"
    html = f"""
<ul class="news-list">
<li>
<time datetime=" 2026-07-07 " class="news-date">JP</time>
<div class="news-text"><a href="/news/press/x/">{real_title}</a></div>
</li>
</ul>
"""
    orig_http = P._http_get
    P._http_get = lambda url, timeout=None: html
    try:
        articles = list(P.PpcDriver().fetch(_make_source()))
    finally:
        P._http_get = orig_http
    a = articles[0]
    ok = (
        a.description.startswith("個人情報保護委員会報道発表: ")
        and real_title in a.description
        and len(a.description) >= 30
    )
    _check("e6 description に prefix が付き Stage 1 フィルタ (30 字) を通す",
           ok, f"len={len(a.description)}, desc={a.description!r}")


def main() -> int:
    print("PPC scraper unit tests (C142)")
    print()
    print("(a) _parse_iso_date:")
    test_parse_iso_date_basic()
    test_parse_iso_date_with_whitespace()
    test_parse_iso_date_invalid_format()
    test_parse_iso_date_out_of_range()

    print()
    print("(b) _normalize_url:")
    test_normalize_url_absolute()
    test_normalize_url_relative_to_absolute()
    test_normalize_url_encodes_space()
    test_normalize_url_empty()
    test_normalize_url_non_http()

    print()
    print("(c) parse_list_page:")
    test_parse_list_returns_3_entries()
    test_parse_list_first_entry()
    test_parse_list_space_url_encoded()
    test_parse_list_absolute_url_preserved()
    test_parse_list_empty_html()
    test_parse_list_no_news_list_returns_empty()

    print()
    print("(d) 定数 sanity:")
    test_host_constant()
    test_list_url_constant()
    test_max_age_days_constant()

    print()
    print("(e) C142: MAX_AGE_DAYS 日付足切り + description prefix:")
    test_driver_default_max_age()
    test_driver_disabled_max_age()
    test_fetch_filters_old_articles()
    test_fetch_pub_date_none_permissive()
    test_fetch_disabled_max_age_passes_old()
    test_fetch_description_prefix_added()

    print()
    print(f"=== {PASS} passed, {FAIL} failed ===")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
