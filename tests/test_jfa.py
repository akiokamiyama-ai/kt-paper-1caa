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
    print(f"=== {PASS} passed, {FAIL} failed ===")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
