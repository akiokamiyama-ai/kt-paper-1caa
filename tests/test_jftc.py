"""Unit tests for scripts.lib.drivers.jftc (C120, Sprint 11, 2026-07-04).

固定 HTML fixture でパース関数の挙動を検証する（ネットワーク不要）。

Run::

    python3 -m tests.test_jftc
"""

from __future__ import annotations

from datetime import date

from scripts.lib.drivers import jftc as J

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
# (a) 令和 → 西暦変換
# ---------------------------------------------------------------------------

def test_reiwa_1_is_2019():
    _check("a1 令和1年 = 2019", J._reiwa_to_gregorian(1, 5, 1) == date(2019, 5, 1))


def test_reiwa_8_is_2026():
    _check("a2 令和8年 = 2026", J._reiwa_to_gregorian(8, 6, 18) == date(2026, 6, 18))


def test_reiwa_invalid_month():
    _check("a3 令和X年 + 13月 → None", J._reiwa_to_gregorian(8, 13, 1) is None)


def test_reiwa_year_zero():
    _check("a4 令和0年（平成扱い、想定外）→ None",
           J._reiwa_to_gregorian(0, 1, 1) is None)


# ---------------------------------------------------------------------------
# (b) parse_index_links
# ---------------------------------------------------------------------------

def test_parse_index_links_basic():
    html = """
    <ul>
      <li>
        <a href="/houdou/pressrelease/2026/jun/260618_spc.html">
          (令和8年6月18日)株式会社エス・ピー・シーに対する勧告について
        </a>
      </li>
      <li>
        <a href="/houdou/pressrelease/2026/jun/260617_kokuji.html">
          (令和8年6月17日)特定荷主が…に関する告示
        </a>
      </li>
    </ul>
    """
    links = J.parse_index_links(html)
    _check("b1 2 リンク抽出", len(links) == 2, f"got {len(links)}")
    _check(
        "b2 first link path",
        links[0][0] == "/houdou/pressrelease/2026/jun/260618_spc.html",
        f"got {links[0][0]!r}",
    )
    _check(
        "b3 first link title (改行 / 空白は保持でも許容)",
        "エス・ピー・シー" in links[0][1],
        f"got {links[0][1][:80]!r}",
    )


def test_parse_index_links_skips_external():
    """外部リンク・他パスは無視される."""
    html = '''
    <a href="https://www.jftc.go.jp/en/">English</a>
    <a href="/houdou/nenpou/2025_report.html">年次報告</a>
    <a href="/houdou/pressrelease/2026/jul/260702_spc.html">7月記事</a>
    '''
    links = J.parse_index_links(html)
    _check(
        "b4 pressrelease パス以外は除外（1 件のみ）",
        len(links) == 1 and "260702_spc" in links[0][0],
        f"got {[l[0] for l in links]}",
    )


# ---------------------------------------------------------------------------
# (c) parse_article_page
# ---------------------------------------------------------------------------

_SAMPLE_ARTICLE = """
<html>
<head><title>(令和8年6月18日)株式会社エス・ピー・シーに対する勧告について | 公正取引委員会</title></head>
<body>
    <div class="p_title">
        <h1>(令和8年6月18日)株式会社エス・ピー・シーに対する勧告について</h1>
    </div>
    <p style="text-align: right;">令和8年6月18日 公正取引委員会</p>
    <p>公正取引委員会は、本日、株式会社エス・ピー・シー（以下「エス・ピー・シー」）に対し、下請代金支払遅延等防止法に基づく勧告を行った。</p>
    <p>エス・ピー・シーは、下請事業者に対し、令和8年3月から令和8年5月までの3ヶ月間、下請代金を減じていた。</p>
    <h2>関連ファイル</h2>
    <ul><li><a href="foo.pdf">別紙</a></li></ul>
    <h2>問い合わせ先</h2>
    <p>取引企画課 電話 03-3581-XXXX</p>
</body>
</html>
"""


def test_parse_article_title_stripped():
    parsed = J.parse_article_page(_SAMPLE_ARTICLE, "https://www.jftc.go.jp/x.html")
    _check(
        "c1 title から (令和X年M月D日) prefix が剥がれる",
        parsed and parsed["title"] == "株式会社エス・ピー・シーに対する勧告について",
        f"got {parsed and parsed['title']!r}",
    )


def test_parse_article_date():
    parsed = J.parse_article_page(_SAMPLE_ARTICLE, "https://www.jftc.go.jp/x.html")
    _check(
        "c2 pub_date = 2026-06-18 (令和8年6月18日 → 西暦)",
        parsed and parsed["pub_date"] == date(2026, 6, 18),
        f"got {parsed and parsed['pub_date']!r}",
    )


def test_parse_article_body_contains_content():
    parsed = J.parse_article_page(_SAMPLE_ARTICLE, "https://www.jftc.go.jp/x.html")
    body = parsed and parsed["body"] or ""
    _check(
        "c3 body に本文が含まれる",
        "下請代金" in body and "勧告" in body,
        f"body preview: {body[:100]!r}",
    )
    _check(
        "c4 body に「関連ファイル」以降は含まれない",
        "問い合わせ先" not in body and "電話" not in body,
        f"body preview: {body[:200]!r}",
    )


def test_parse_article_no_h1_returns_none():
    _check(
        "c5 h1 無しの HTML → None",
        J.parse_article_page("<html><body>no h1</body></html>", "x") is None,
    )


# ---------------------------------------------------------------------------
# (d) 定数 sanity
# ---------------------------------------------------------------------------

def test_host_constant():
    _check("d1 HOST 定数", J.HOST == "www.jftc.go.jp")


def test_month_map_full():
    _check(
        "d2 月マップ 12 月分全て収録",
        len(J._MONTH_EN_ABBREV) == 12
        and J._MONTH_EN_ABBREV[6] == "jun"
        and J._MONTH_EN_ABBREV[7] == "jul",
    )


def main() -> int:
    print("JFTC scraper unit tests (C120)")
    print()
    print("(a) 令和 → 西暦:")
    test_reiwa_1_is_2019()
    test_reiwa_8_is_2026()
    test_reiwa_invalid_month()
    test_reiwa_year_zero()

    print()
    print("(b) parse_index_links:")
    test_parse_index_links_basic()
    test_parse_index_links_skips_external()

    print()
    print("(c) parse_article_page:")
    test_parse_article_title_stripped()
    test_parse_article_date()
    test_parse_article_body_contains_content()
    test_parse_article_no_h1_returns_none()

    print()
    print("(d) 定数 sanity:")
    test_host_constant()
    test_month_map_full()

    print()
    print(f"=== {PASS} passed, {FAIL} failed ===")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
