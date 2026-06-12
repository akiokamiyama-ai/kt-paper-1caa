"""Unit tests for ``Article.to_pipeline_dict()`` (C80c, Fable review M1).

Sprint 9 で page1 / page3 / stage1 に分散していた pipeline_dict 構築を
``Article.to_pipeline_dict()`` に一本化（M1 修正）。本テストは：

- 基本フィールド構成
- ``source_language`` が常に含まれる
- ``raw["tribune_category"]`` の自動伝播（C76 / C79 同等動作）
- description / body の override 引数
- 既存 3 経路で同じ shape

を検証する。

Run::

    python3 -m tests.lib.test_to_pipeline_dict
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone

from scripts.lib.source import Article

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


def _make_article(**overrides) -> Article:
    base = dict(
        source_name="BBC Business",
        title="Sample title",
        link="https://bbc.com/news/x",
        description="raw <p>description</p>",
        pub_date=datetime(2026, 6, 12, 9, 0, tzinfo=timezone.utc),
        source_language="en",
        raw={},
    )
    base.update(overrides)
    return Article(**base)


# ---------------------------------------------------------------------------
# (a) 基本フィールド構成
# ---------------------------------------------------------------------------

def test_basic_fields_present():
    art = _make_article()
    d = art.to_pipeline_dict()
    expected_keys = {
        "url", "title", "description", "body",
        "source_name", "source_url", "pub_date", "source_language",
    }
    actual_keys = set(d.keys())
    _check(
        "a1 基本 8 フィールドが全て含まれる",
        actual_keys >= expected_keys,
        f"missing: {expected_keys - actual_keys}",
    )


def test_link_is_mapped_to_url():
    """``Article.link`` → ``pipeline_dict["url"]``."""
    art = _make_article(link="https://example.test/x")
    d = art.to_pipeline_dict()
    _check("a2 link → url にマッピング", d["url"] == "https://example.test/x")


def test_source_url_always_none():
    """source_url は常に None (selector 側で registry から埋める)."""
    art = _make_article()
    d = art.to_pipeline_dict()
    _check("a3 source_url=None", d["source_url"] is None)


def test_pub_date_isoformat_or_none():
    art1 = _make_article(pub_date=datetime(2026, 6, 12, tzinfo=timezone.utc))
    art2 = _make_article(pub_date=None)
    _check("a4 pub_date 有 → isoformat 文字列",
           art1.to_pipeline_dict()["pub_date"] == "2026-06-12T00:00:00+00:00")
    _check("a5 pub_date None → None",
           art2.to_pipeline_dict()["pub_date"] is None)


# ---------------------------------------------------------------------------
# (b) source_language は常に含まれる
# ---------------------------------------------------------------------------

def test_source_language_always_present():
    """page3 default_fetcher 経路でも source_language が含まれる
    （旧 page3 経路は欠落していたが、害なし）."""
    art = _make_article(source_language="ja")
    _check(
        "b1 source_language='ja' が含まれる",
        art.to_pipeline_dict()["source_language"] == "ja",
    )
    art_en = _make_article(source_language="en")
    _check(
        "b2 source_language='en' が含まれる",
        art_en.to_pipeline_dict()["source_language"] == "en",
    )


# ---------------------------------------------------------------------------
# (c) raw["tribune_category"] の動的伝播（C76 / C79）
# ---------------------------------------------------------------------------

def test_tribune_category_propagates_to_category_field():
    """driver が raw[tribune_category] をセットしている場合、
    pipeline_dict[category] に自動反映."""
    art = _make_article(raw={"tribune_category": "business",
                              "category_que": "経済・ビジネス"})
    d = art.to_pipeline_dict()
    _check("c1 raw[tribune_category]='business' → category='business'",
           d.get("category") == "business")


def test_tribune_category_geopolitics():
    art = _make_article(raw={"tribune_category": "geopolitics"})
    d = art.to_pipeline_dict()
    _check("c2 raw[tribune_category]='geopolitics' → category='geopolitics'",
           d.get("category") == "geopolitics")


def test_no_tribune_category_no_category_key():
    """driver が tribune_category をセットしない通常 RSS は category キーなし
    （selector._attach_category / _category_of の registry fallback を維持）."""
    art = _make_article(raw={})
    d = art.to_pipeline_dict()
    _check("c3 raw 空 → category キーなし（registry fallback パス維持）",
           "category" not in d, f"got {d}")


def test_empty_raw_field_safe():
    """raw が空 dict / None どちらでも crash しない."""
    art = _make_article(raw=None)
    d = art.to_pipeline_dict()
    _check("c4 raw=None でも crash せず category キーなし",
           "category" not in d, f"got {d}")


# ---------------------------------------------------------------------------
# (d) description / body の override
# ---------------------------------------------------------------------------

def test_description_override_used():
    art = _make_article(description="raw <p>description</p>")
    d = art.to_pipeline_dict(description="cleaned description")
    _check("d1 description override 適用",
           d["description"] == "cleaned description")


def test_description_default_passes_raw():
    art = _make_article(description="raw <p>description</p>")
    d = art.to_pipeline_dict()
    _check("d2 description override 無 → raw 値をそのまま",
           d["description"] == "raw <p>description</p>")


def test_body_override_used():
    art = _make_article()
    art.body_paragraphs = ["p1", "p2"]
    d = art.to_pipeline_dict(body="single clean body")
    _check("d3 body override 適用", d["body"] == "single clean body")


def test_body_default_joins_paragraphs():
    art = _make_article()
    art.body_paragraphs = ["第一段落", "第二段落"]
    d = art.to_pipeline_dict()
    _check("d4 body override 無 → body_paragraphs を改行結合",
           d["body"] == "第一段落\n第二段落")


def test_body_default_empty_when_no_paragraphs():
    art = _make_article()
    d = art.to_pipeline_dict()
    _check("d5 body_paragraphs 空 → body=''",
           d["body"] == "")


# ---------------------------------------------------------------------------
# (e) 3 経路で同じ shape（M1 一本化の確認）
# ---------------------------------------------------------------------------

def test_three_paths_share_same_shape():
    """page1 _article_to_pipeline_dict / page3 default_fetcher / stage1 _to_dict
    の 3 経路が全て Article.to_pipeline_dict() に集約されたことを確認.
    """
    from scripts.regen_front_page_v2 import _article_to_pipeline_dict
    from scripts.selector.stage1 import _to_dict as stage1_to_dict

    art = _make_article(
        description="raw description with no tags",
        raw={"tribune_category": "business"},
    )

    d_page1 = _article_to_pipeline_dict(art)
    d_stage1 = stage1_to_dict(art)
    # page3 経路は default_fetcher 内 inline。直接 to_pipeline_dict を呼んで
    # 同じ shape が返ることを確認（stripping は経路固有のため別途）。
    d_p3_like = art.to_pipeline_dict(
        description="raw description with no tags",
        body="",
    )

    common_keys = {"url", "title", "source_name", "source_url",
                   "pub_date", "source_language", "category"}
    _check(
        "e1 page1 / stage1 / page3-like 経路で共通キー集合が一致",
        all(k in d for d in (d_page1, d_stage1, d_p3_like) for k in common_keys),
        f"page1={set(d_page1.keys())} stage1={set(d_stage1.keys())} "
        f"p3={set(d_p3_like.keys())}",
    )
    _check(
        "e2 tribune_category=business が 3 経路全てで category に反映",
        d_page1.get("category") == "business"
        and d_stage1.get("category") == "business"
        and d_p3_like.get("category") == "business",
    )


def main() -> int:
    print("Article.to_pipeline_dict() unit tests (C80c, Fable review M1)")
    print()
    print("(a) 基本フィールド構成:")
    test_basic_fields_present()
    test_link_is_mapped_to_url()
    test_source_url_always_none()
    test_pub_date_isoformat_or_none()

    print()
    print("(b) source_language は常に含まれる:")
    test_source_language_always_present()

    print()
    print("(c) raw[tribune_category] 動的伝播:")
    test_tribune_category_propagates_to_category_field()
    test_tribune_category_geopolitics()
    test_no_tribune_category_no_category_key()
    test_empty_raw_field_safe()

    print()
    print("(d) description / body override:")
    test_description_override_used()
    test_description_default_passes_raw()
    test_body_override_used()
    test_body_default_joins_paragraphs()
    test_body_default_empty_when_no_paragraphs()

    print()
    print("(e) 3 経路で同じ shape:")
    test_three_paths_share_same_shape()

    print()
    print(f"=== {PASS} passed, {FAIL} failed ===")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
