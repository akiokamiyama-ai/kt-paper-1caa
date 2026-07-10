"""Unit tests for scripts.lib.drivers.jfa (C127, 2026-07-09).

固定 HTML fixture でパース関数の挙動を検証。ネットワーク不要。

Run::

    python3 -m tests.test_jfa
"""

from __future__ import annotations

from datetime import date

from scripts.lib.drivers import jfa as J

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
# (a) _parse_ymd_dot
# ---------------------------------------------------------------------------

def test_parse_ymd_dot_basic():
    _check("a1 2026.06.22 → date(2026,6,22)",
           J._parse_ymd_dot("2026.06.22") == date(2026, 6, 22))


def test_parse_ymd_dot_invalid():
    _check("a2 不正フォーマット → None",
           J._parse_ymd_dot("2026/06/22") is None)


def test_parse_ymd_dot_out_of_range():
    _check("a3 存在しない日 (2026.13.01) → None",
           J._parse_ymd_dot("2026.13.01") is None)


# ---------------------------------------------------------------------------
# (b) parse_list_page
# ---------------------------------------------------------------------------

_SAMPLE_LIST = """
<article>
<div class="newsList_ttl"><h1>新着情報</h1></div>
<dl class="newsList">
<dt>2026.06.22</dt>
<dd><h2><a href="https://www.jfa-fc.or.jp/particle/320.html">コンビニエンスストア統計調査5月度</a></h2></dd>
<dt>2026.06.02</dt>
<dd><h2><a href="https://www.jfa-fc.or.jp/particle/5208.html" title="共同宣言...">「まちの安全・安心ステーション東京」共同宣言に伴うコンビニエンスストア合同防犯訓練実施について</a></h2></dd>
<dt>2026.05.20</dt>
<dd><h2><a href="/particle/320.html">コンビニエンスストア統計調査4月度</a></h2></dd>
</dl>
</article>
"""


def test_parse_list_returns_3_entries():
    entries = J.parse_list_page(_SAMPLE_LIST)
    _check("b1 3 エントリ抽出", len(entries) == 3, f"got {len(entries)}")


def test_parse_list_first_entry_absolute_url():
    entries = J.parse_list_page(_SAMPLE_LIST)
    e = entries[0]
    _check("b2 最初の URL (絶対)",
           e["url"] == "https://www.jfa-fc.or.jp/particle/320.html",
           f"got {e['url']!r}")
    _check("b3 最初の title",
           e["title"] == "コンビニエンスストア統計調査5月度",
           f"got {e['title']!r}")
    _check("b4 最初の date",
           e["date"] == date(2026, 6, 22),
           f"got {e['date']!r}")


def test_parse_list_relative_url_absolutized():
    """3 番目のエントリは相対 URL / 絶対 URL に補完されるか."""
    entries = J.parse_list_page(_SAMPLE_LIST)
    e = entries[2]
    _check("b5 相対 URL → 絶対 URL 補完",
           e["url"].startswith("https://www.jfa-fc.or.jp/"),
           f"got {e['url']!r}")


def test_parse_list_empty_html():
    _check("b6 空 HTML → 空リスト", J.parse_list_page("") == [])


def test_parse_list_no_dl_returns_empty():
    _check("b7 dt/dd 構造なし → 空リスト",
           J.parse_list_page("<html><body>no dl</body></html>") == [])


# ---------------------------------------------------------------------------
# (c) 定数
# ---------------------------------------------------------------------------

def test_host_constant():
    _check("c1 HOST", J.HOST == "www.jfa-fc.or.jp")


def test_list_url_constant():
    _check("c2 LIST_URL は release/1 を指す",
           "release/1" in J.LIST_URL)


# ---------------------------------------------------------------------------
# (d) C140 (Sprint 12, 2026-07-10): MAX_AGE_DAYS 日付足切り
# ---------------------------------------------------------------------------

def _make_source():
    from scripts.lib.source import Source, Priority, Status, FetchMethod
    return Source(
        name="JFA", url=f"https://{J.HOST}/",
        category="companies:Web-Repo",
        priority=Priority.MEDIUM, status=Status.PARTIAL,
        fetch_method=FetchMethod.HTML, site_file="companies.md",
    )


def test_max_age_days_constant():
    _check("d1 DEFAULT_MAX_AGE_DAYS = 90",
           J.DEFAULT_MAX_AGE_DAYS == 90)


def test_driver_default_max_age():
    d = J.JfaDriver()
    _check("d2 driver default max_age_days = 90", d.max_age_days == 90)


def test_driver_disabled_max_age():
    d = J.JfaDriver(max_age_days=None)
    _check("d3 max_age_days=None で足切り無効", d.max_age_days is None)


def test_fetch_filters_old_articles(monkeypatch_shim=None):
    """C140: 90 日超の記事は除外、90 日以内は通る."""
    # Freeze "today" via a real fetch mock. Stub _http_get to return
    # a list page with mixed old / new dates.
    from datetime import date, timedelta
    ref_today = date(2026, 7, 10)
    # Bracket: 89 days ago = pass, 91 days ago = skip
    ok_date = ref_today - timedelta(days=89)
    old_date = ref_today - timedelta(days=91)
    html = f"""
<dl class="newsList">
<dt>{ok_date.year}.{ok_date.month:02d}.{ok_date.day:02d}</dt>
<dd><h2><a href="https://{J.HOST}/particle/new.html">新しい記事</a></h2></dd>
<dt>{old_date.year}.{old_date.month:02d}.{old_date.day:02d}</dt>
<dd><h2><a href="https://{J.HOST}/particle/old.html">古い記事</a></h2></dd>
</dl>
"""
    orig_http = J._http_get
    from datetime import datetime as _dt
    orig_dt = J.datetime
    J._http_get = lambda url, timeout=None: html

    class _FakeDatetime(_dt):
        @classmethod
        def now(cls, tz=None):
            return _dt.combine(ref_today, _dt.min.time(), tzinfo=tz)
    J.datetime = _FakeDatetime
    try:
        articles = list(J.JfaDriver().fetch(_make_source()))
    finally:
        J._http_get = orig_http
        J.datetime = orig_dt
    urls = [a.link for a in articles]
    _check("d4 89 日前は通る、91 日前は除外",
           len(articles) == 1 and articles[0].link.endswith("/new.html"),
           f"got urls={urls}")


def test_fetch_pub_date_none_permissive():
    """C140: pub_date が None なら permissive に通す（driver parse 失敗の防御）.

    ``_ENTRY_RE`` は形式的な YMD (``\\d{4}\\.\\d{2}\\.\\d{2}``) を要求するが
    ``_parse_ymd_dot`` は存在しない日 (``2026.13.01`` = 13 月) には None を
    返す。この「regex は match するが date は None」ケースで日付足切りが
    permissive に働くことを確認。
    """
    html = f"""
<dl class="newsList">
<dt>2026.13.01</dt>
<dd><h2><a href="https://{J.HOST}/particle/x.html">日付不明</a></h2></dd>
</dl>
"""
    orig_http = J._http_get
    J._http_get = lambda url, timeout=None: html
    try:
        articles = list(J.JfaDriver().fetch(_make_source()))
    finally:
        J._http_get = orig_http
    _check("d5 pub_date=None (parse 失敗) は permissive に通す",
           len(articles) == 1 and articles[0].pub_date is None,
           f"got {len(articles)} articles, pub_date={articles[0].pub_date if articles else 'N/A'}")


def test_fetch_disabled_max_age_passes_old():
    """C140: max_age_days=None なら 100 日前記事も通る (足切り無効)."""
    from datetime import date, timedelta
    ref_today = date(2026, 7, 10)
    old_date = ref_today - timedelta(days=100)
    html = f"""
<dl class="newsList">
<dt>{old_date.year}.{old_date.month:02d}.{old_date.day:02d}</dt>
<dd><h2><a href="https://{J.HOST}/particle/old.html">古い記事</a></h2></dd>
</dl>
"""
    orig_http = J._http_get
    J._http_get = lambda url, timeout=None: html
    try:
        articles = list(J.JfaDriver(max_age_days=None).fetch(_make_source()))
    finally:
        J._http_get = orig_http
    _check("d6 max_age_days=None で 100 日前記事も通る",
           len(articles) == 1)


def main() -> int:
    print("JFA scraper unit tests (C127)")
    print()
    print("(a) _parse_ymd_dot:")
    test_parse_ymd_dot_basic()
    test_parse_ymd_dot_invalid()
    test_parse_ymd_dot_out_of_range()

    print()
    print("(b) parse_list_page:")
    test_parse_list_returns_3_entries()
    test_parse_list_first_entry_absolute_url()
    test_parse_list_relative_url_absolutized()
    test_parse_list_empty_html()
    test_parse_list_no_dl_returns_empty()

    print()
    print("(c) 定数:")
    test_host_constant()
    test_list_url_constant()

    print()
    print("(d) C140: MAX_AGE_DAYS 日付足切り:")
    test_max_age_days_constant()
    test_driver_default_max_age()
    test_driver_disabled_max_age()
    test_fetch_filters_old_articles()
    test_fetch_pub_date_none_permissive()
    test_fetch_disabled_max_age_passes_old()

    print()
    print(f"=== {PASS} passed, {FAIL} failed ===")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
