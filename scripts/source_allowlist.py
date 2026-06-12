"""Single source of truth for Page I candidates / Today's Headlines allowlists.

C81 段階 1 (Sprint 9, 2026-06-13, Fable review M6 god module 分割の第一弾):
``SOURCE_NAME_FILTERS`` (旧 regen_front_page_v2.py) と
``HEADLINES_ALLOWED_SOURCES`` (旧 selector/todays_headlines.py) が別ファイルで
定義されており、手動同期に依存していた。これが C78 真因「page1 candidates に
QUE が流入していないため Headlines pool にも届かない」の構造的原因だった。
本モジュールに集約し、両者の整合性を構造的に保証する。

設計
====

3 つの allowlist
-----------------

- ``SOURCE_NAME_FILTERS``: page1 ``fetch_candidates`` の substring filter
  （``fetch.run(name_substring=...)`` に渡される loose match）。``NHK ニュース``
  が「NHK ニュース 主要」「NHK ニュース 経済」両方を拾うように、prefix で
  複数 source を捕捉する。
- ``HEADLINES_ALLOWED_SOURCES``: Today's Headlines pool 化時の **完全一致** allowlist
  （``article["source_name"]`` に対する厳密 match）。
- ``HEADLINES_SOURCE_CATEGORY_RESTRICT``: per-source category 制限。Shincho QUE は
  記事ごとに category 動的（C76）なので、Headlines に流入させたい category のみ通す。

不変条件
--------

「SOURCE_NAME_FILTERS は HEADLINES_ALLOWED_SOURCES が指す source を全部取得できる
ような上位集合」という関係を ``check_allowlist_consistency()`` で検証可能。
将来 source を追加するときは本ファイル 1 箇所だけ更新すれば 2 系統に同時反映
される（C78 タイプの「片側更新漏れ」を構造的に予防）。
"""

from __future__ import annotations


# substring filters used by page1 fetch_candidates (loose match against
# Source.name; "NHK ニュース" matches both 主要 and 経済, "Shincho QUE" matches
# "Shincho QUE（新潮QUE）")
SOURCE_NAME_FILTERS: tuple[str, ...] = (
    "BBC Business",
    "The Economist",
    "Foresight",        # 旧 新潮社 FORESIGHT (C12), 現状は新潮 QUE に統合だが
                        # 名前は維持 (sources/geopolitics.md の H3 名で fetch される)
    "Financial Times",  # C75: business.md FT を candidates に流入
    "NHK ニュース",       # C75: 主要 + 経済 を両方拾う、cooking は除外
    "Yahoo! ニュース",    # C75: 経済欄を candidates に流入
    "Shincho QUE",       # C79: QUE 動的 category マッピングで business のみ Headlines 候補に
)

# exact-match allowlist for Today's Headlines (article["source_name"] に対する厳密一致)
HEADLINES_ALLOWED_SOURCES: tuple[str, ...] = (
    "NHK ニュース 主要",
    "NHK ニュース 経済",
    "Yahoo! ニュース 経済",
    "BBC Business",
    "The Economist",
    "Financial Times（FT）",   # C75
    "Shincho QUE（新潮QUE）",  # C76 + C79
)

# per-source category restriction. QUE のみが動的 category を持ち、Headlines に
# 流入させたい category（business = 国内系）のみ通す。Foresight / 国際系
# （category=geopolitics）は page3 R1/R3 へ振り分けされる。
HEADLINES_SOURCE_CATEGORY_RESTRICT: dict[str, tuple[str, ...]] = {
    "Shincho QUE（新潮QUE）": ("business",),
}


def check_allowlist_consistency() -> list[str]:
    """Return a list of inconsistencies, empty list if all is well.

    検証内容:
    - HEADLINES_ALLOWED_SOURCES の各 source.name が、いずれかの
      SOURCE_NAME_FILTERS の substring を含むこと（fetch 経路でカバーされるか）。
    - HEADLINES_SOURCE_CATEGORY_RESTRICT の key が HEADLINES_ALLOWED_SOURCES に
      含まれていること（無関係な source への restriction を防ぐ）。
    """
    issues: list[str] = []
    for headline_src in HEADLINES_ALLOWED_SOURCES:
        if not any(f in headline_src for f in SOURCE_NAME_FILTERS):
            issues.append(
                f"{headline_src!r} in HEADLINES_ALLOWED_SOURCES has no matching "
                f"prefix in SOURCE_NAME_FILTERS (will not flow into page1 "
                f"candidates_scored → Today's Headlines pool 到達不可能)"
            )
    for restrict_src in HEADLINES_SOURCE_CATEGORY_RESTRICT:
        if restrict_src not in HEADLINES_ALLOWED_SOURCES:
            issues.append(
                f"{restrict_src!r} in HEADLINES_SOURCE_CATEGORY_RESTRICT is "
                f"not in HEADLINES_ALLOWED_SOURCES (restriction has no effect)"
            )
    return issues
