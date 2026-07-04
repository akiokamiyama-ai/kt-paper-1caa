"""Unit tests for scripts.lib.drivers.fitness_business (C122, 2026-07-04).

固定 HTML/XML fixture で parse 関数の挙動を検証。ネットワーク不要。

Run::

    python3 -m tests.test_fitness_business
"""

from __future__ import annotations

from datetime import datetime

from scripts.lib.drivers import fitness_business as F

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
# (a) parse_sitemap_articles
# ---------------------------------------------------------------------------

_SAMPLE_SITEMAP = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
<url><loc>https://business.fitnessclub.jp</loc><lastmod>2026-07-04T00:00:00+09:00</lastmod></url>
<url><loc>https://business.fitnessclub.jp/articles/-/2776</loc><lastmod>2026-07-03T10:00:00+09:00</lastmod></url>
<url><loc>https://business.fitnessclub.jp/articles/-/2781</loc><lastmod>2026-07-04T09:00:00+09:00</lastmod></url>
<url><loc>https://business.fitnessclub.jp/articles/-/2775</loc><lastmod>2026-06-30T00:00:00+09:00</lastmod></url>
<url><loc>https://business.fitnessclub.jp/category/news</loc><lastmod>2026-07-04T00:00:00+09:00</lastmod></url>
</urlset>
"""


def test_sitemap_filters_only_articles():
    """記事以外の URL (/, /category/news) は除外."""
    entries = F.parse_sitemap_articles(_SAMPLE_SITEMAP)
    _check(
        "a1 記事 URL のみ抽出（3 件、トップ / category は除外）",
        len(entries) == 3,
        f"got {len(entries)}",
    )
    for url, _ in entries:
        _check(f"a1b URL contains /articles/-/ : {url}",
               "/articles/-/" in url)


def test_sitemap_sorted_by_lastmod_desc():
    """lastmod 降順で並ぶ."""
    entries = F.parse_sitemap_articles(_SAMPLE_SITEMAP)
    _check(
        "a2 lastmod 降順（2781 最新 → 2776 → 2775）",
        entries[0][0].endswith("/2781")
        and entries[1][0].endswith("/2776")
        and entries[2][0].endswith("/2775"),
        f"got order: {[u.split('/')[-1] for u,_ in entries]}",
    )


_SAMPLE_SITEMAP_NO_LASTMOD = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
<url><loc>https://business.fitnessclub.jp/articles/-/2776</loc></url>
<url><loc>https://business.fitnessclub.jp/articles/-/2781</loc></url>
<url><loc>https://business.fitnessclub.jp/articles/-/2775</loc></url>
<url><loc>https://business.fitnessclub.jp/articles/-/2500</loc></url>
</urlset>
"""


def test_sitemap_no_lastmod_falls_back_to_id_desc():
    """実サイトの sitemap には lastmod 無し → ID 降順 fallback."""
    entries = F.parse_sitemap_articles(_SAMPLE_SITEMAP_NO_LASTMOD)
    _check(
        "a3 lastmod 無しは ID 降順（2781 → 2776 → 2775 → 2500）",
        len(entries) == 4
        and entries[0][0].endswith("/2781")
        and entries[1][0].endswith("/2776")
        and entries[2][0].endswith("/2775")
        and entries[3][0].endswith("/2500"),
        f"got {[u.split('/')[-1] for u,_ in entries]}",
    )


# ---------------------------------------------------------------------------
# (b) parse_article_page
# ---------------------------------------------------------------------------

_SAMPLE_ARTICLE_JSONLD = """
<html>
<head>
<title>フィットネス市場、緩やかに回復へ | Fitness Business</title>
<meta name="description" content="日本の余暇の動向を総合的に把握できるデータが満載されている『レジャー白書』が、今年も10月31日に刊行された。">
<meta property="og:description" content="og version description here">
<script type="application/ld+json">
[{"@context":"http://schema.org","@type":"WebSite","name":"Fitness Business"},
{"@context":"http://schema.org","@type":"Article","headline":"フィットネス市場、緩やかに回復へ","datePublished":"2024-11-25T00:00:00+09:00","dateModified":"2024-11-24T15:18:04+09:00","description":"日本の余暇の動向を総合的に把握できるデータが満載されている『レジャー白書』が刊行された。"}]
</script>
</head>
<body>
<h1></h1>
<h1>フィットネス市場、緩やかに回復へ</h1>
</body>
</html>
"""


def test_article_title_from_jsonld():
    p = F.parse_article_page(
        _SAMPLE_ARTICLE_JSONLD, "https://business.fitnessclub.jp/articles/-/2318",
    )
    _check(
        "b1 title = JSON-LD headline",
        p and p["title"] == "フィットネス市場、緩やかに回復へ",
        f"got {p and p['title']!r}",
    )


def test_article_pub_dt_from_jsonld():
    p = F.parse_article_page(_SAMPLE_ARTICLE_JSONLD, "x")
    _check(
        "b2 pub_dt = 2024-11-25T00:00:00+09:00 (JSON-LD datePublished)",
        p and isinstance(p["pub_dt"], datetime)
        and p["pub_dt"].year == 2024 and p["pub_dt"].month == 11
        and p["pub_dt"].day == 25,
        f"got {p and p['pub_dt']!r}",
    )


def test_article_body_from_jsonld():
    p = F.parse_article_page(_SAMPLE_ARTICLE_JSONLD, "x")
    body = p and p["body"] or ""
    _check(
        "b3 body 冒頭に「日本の余暇の動向」（JSON-LD description）",
        "レジャー白書" in body,
        f"body preview: {body[:120]!r}",
    )


_SAMPLE_ARTICLE_META_ONLY = """
<html>
<head>
<title>タイトル無 JSON-LD | Fitness Business</title>
<meta name="description" content="meta description only fallback text">
</head>
<body>
<h1>本文タイトル h1 で拾う</h1>
</body>
</html>
"""


def test_article_fallback_to_h1_and_meta():
    """JSON-LD 無 → h1 でタイトル、meta で body."""
    p = F.parse_article_page(_SAMPLE_ARTICLE_META_ONLY, "x")
    _check(
        "b4 JSON-LD 無 → h1 でタイトル",
        p and p["title"] == "本文タイトル h1 で拾う",
        f"got {p and p['title']!r}",
    )
    _check(
        "b5 JSON-LD 無 → meta description で body",
        p and "meta description only" in (p["body"] or ""),
        f"got {p and p['body'][:80]!r}",
    )


def test_article_fallback_to_title_tag():
    """h1 空 + JSON-LD 無 → <title> から Fitness Business suffix 剥がす."""
    html = """
    <html>
    <head><title>タイトルのみ | Fitness Business</title></head>
    <body><h1></h1></body>
    </html>
    """
    p = F.parse_article_page(html, "x")
    _check(
        "b6 <title> fallback、「| Fitness Business」suffix 剥がし",
        p and p["title"] == "タイトルのみ",
        f"got {p and p['title']!r}",
    )


def test_article_no_title_returns_none():
    _check(
        "b7 title 一切なし → None",
        F.parse_article_page("<html><body>x</body></html>", "y") is None,
    )


# ---------------------------------------------------------------------------
# (c) 定数
# ---------------------------------------------------------------------------

def test_host_constant():
    _check("c1 HOST", F.HOST == "business.fitnessclub.jp")


def test_sitemap_url_constant():
    _check(
        "c2 SITEMAP_URL",
        F.SITEMAP_URL == "https://business.fitnessclub.jp/sitemap.xml",
    )


def main() -> int:
    print("FitnessBusiness scraper unit tests (C122)")
    print()
    print("(a) parse_sitemap_articles:")
    test_sitemap_filters_only_articles()
    test_sitemap_sorted_by_lastmod_desc()
    test_sitemap_no_lastmod_falls_back_to_id_desc()

    print()
    print("(b) parse_article_page:")
    test_article_title_from_jsonld()
    test_article_pub_dt_from_jsonld()
    test_article_body_from_jsonld()
    test_article_fallback_to_h1_and_meta()
    test_article_fallback_to_title_tag()
    test_article_no_title_returns_none()

    print()
    print("(c) 定数:")
    test_host_constant()
    test_sitemap_url_constant()

    print()
    print(f"=== {PASS} passed, {FAIL} failed ===")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
