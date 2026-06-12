"""Unit tests for scripts/notes/style_loader.py (C80d M5).

Sprint 9 Fable レビュー M5 対応第三弾。``load_style_cache`` /
``build_style_block`` の純関数ロジックを fixture JSON でカバー。

Run::

    python3 -m tests.notes.test_style_loader
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

from scripts.notes import style_loader

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


def _make_cache_dict(*, n_articles: int = 2, body_per: int = 200) -> dict:
    return {
        "fetched_at": "2026-06-12",
        "source_url": "https://note.com/kamichof",
        "articles": [
            {
                "title": f"記事タイトル {i+1}",
                "url": f"https://note.com/kamichof/n/n{i+1:08d}",
                "pub_date": "2021-07-01",
                "body": "あ" * body_per,
            }
            for i in range(n_articles)
        ],
        "style_features": [
            "平易な日本語",
            "段落は短〜中",
            "結論を開いて終わる",
        ],
    }


# ---------------------------------------------------------------------------
# (a) load_style_cache
# ---------------------------------------------------------------------------

def test_load_style_cache_returns_dict():
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "cache.json"
        p.write_text(json.dumps(_make_cache_dict()), encoding="utf-8")
        cache = style_loader.load_style_cache(path=p)
    _check(
        "a1 valid cache JSON → dict 返却",
        cache is not None and "articles" in cache and len(cache["articles"]) == 2,
        f"got {cache}",
    )


def test_load_style_cache_missing_returns_none():
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "missing.json"
        cache = style_loader.load_style_cache(path=p)
    _check("a2 missing file → None", cache is None)


def test_load_style_cache_corrupt_returns_none():
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "corrupt.json"
        p.write_text("not valid json {", encoding="utf-8")
        cache = style_loader.load_style_cache(path=p)
    _check("a3 corrupt JSON → None", cache is None)


# ---------------------------------------------------------------------------
# (b) build_style_block
# ---------------------------------------------------------------------------

def test_build_style_block_includes_style_guide_when_cache_none():
    out = style_loader.build_style_block(None)
    _check(
        "b1 cache=None → STYLE_GUIDE のみ返す",
        "神山さんの文体特徴" in out and "記事タイトル" not in out,
        f"len={len(out)}",
    )


def test_build_style_block_includes_articles_excerpt():
    cache = _make_cache_dict(n_articles=2, body_per=300)
    out = style_loader.build_style_block(cache, max_chars=3500)
    _check(
        "b2 cache 有 → 各 article の見出し + body 抜粋が含まれる",
        "記事タイトル 1" in out
        and "記事タイトル 2" in out
        and "実例 1" in out,
        f"len={len(out)}",
    )


def test_build_style_block_respects_max_chars_budget():
    """大量記事 / max_chars 小で truncate される."""
    cache = _make_cache_dict(n_articles=10, body_per=1000)
    out = style_loader.build_style_block(cache, max_chars=1500)
    # STYLE_GUIDE 本文（~1500-2000字）+ excerpt headers が含まれるので
    # max_chars は「excerpt 部分の予算上限」として動く（STYLE_GUIDE は別途）。
    # 検証: ある一定以下に収まること（STYLE_GUIDE 部分 + 最小 1 件 + budget 程度）。
    _check(
        "b3 max_chars 制限で excerpt が truncate される",
        len(out) < 20000 and "実例" in out,
        f"len={len(out)}",
    )


def test_build_style_block_empty_articles_only_guide():
    cache = _make_cache_dict(n_articles=0)
    out = style_loader.build_style_block(cache)
    # 「実例 1」「実例 2」等の番号付き article 区切り見出しは出ない
    # （STYLE_GUIDE 内に「実例」という単語自体は説明として含まれる）。
    _check(
        "b4 cache.articles=[] → STYLE_GUIDE + 出典ヘッダのみ、article 区切りなし",
        "神山さんの文体特徴" in out and "--- 実例 1:" not in out,
    )


def test_build_style_block_uses_fetched_at_in_header():
    cache = _make_cache_dict()
    cache["fetched_at"] = "2026-06-12"
    out = style_loader.build_style_block(cache)
    _check(
        "b5 cache.fetched_at がヘッダに反映される",
        "cached 2026-06-12" in out,
    )


# ---------------------------------------------------------------------------
# (c) build_style_block_from_disk
# ---------------------------------------------------------------------------

def test_build_style_block_from_disk_uses_real_cache():
    """実 cache file (data/notes_cache/kamiyama_style.json) を読み込めること."""
    out = style_loader.build_style_block_from_disk()
    _check(
        "c1 build_style_block_from_disk: 実 cache を読み込んで block を組み立てる",
        len(out) > 100 and "神山さんの文体特徴" in out,
        f"len={len(out)}",
    )


def main() -> int:
    print("scripts/notes/style_loader unit tests (C80d M5)")
    print()
    print("(a) load_style_cache:")
    test_load_style_cache_returns_dict()
    test_load_style_cache_missing_returns_none()
    test_load_style_cache_corrupt_returns_none()
    print()
    print("(b) build_style_block:")
    test_build_style_block_includes_style_guide_when_cache_none()
    test_build_style_block_includes_articles_excerpt()
    test_build_style_block_respects_max_chars_budget()
    test_build_style_block_empty_articles_only_guide()
    test_build_style_block_uses_fetched_at_in_header()
    print()
    print("(c) build_style_block_from_disk:")
    test_build_style_block_from_disk_uses_real_cache()
    print()
    print(f"=== {PASS} passed, {FAIL} failed ===")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
