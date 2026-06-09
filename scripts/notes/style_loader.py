"""神山さん文体素材のキャッシュ読み込み（C38b 第二弾, 2026-06-09）。

C38b 第二弾で「神山さん note ブログを参照した文体ガイダンス」を導入。
WebFetch（Claude Code のツール）で取得した記事を JSON にキャッシュし、
本モジュールが読み込んで prompt に注入する文字列を組み立てる。

キャッシュ仕様
----------------

- パス: ``data/notes_cache/kamiyama_style.json``
- スキーマ::

      {
          "fetched_at": "YYYY-MM-DD",
          "source_url": "https://note.com/kamichof",
          "note": "...",
          "articles": [
              {"title": str, "url": str, "pub_date": str, "body": str},
              ...
          ],
          "style_features": [str, ...]
      }

- 永続キャッシュ（毎回 fetch しない）。再取得は手動：
  Claude Code セッションで WebFetch を実行 → ``kamiyama_style.json`` を上書き。

公開関数
----------

- ``load_style_cache()`` : キャッシュを dict として返す。存在しなければ ``None``。
- ``build_style_block(cache, max_chars=3500)`` : prompt 注入用の文字列を作成。
- ``build_style_block_from_disk(max_chars=3500)`` : ロード + 整形のワンライナー。
"""

from __future__ import annotations

import json
from pathlib import Path

from .prompts import STYLE_GUIDE

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
CACHE_PATH = PROJECT_ROOT / "data" / "notes_cache" / "kamiyama_style.json"


def load_style_cache(path: Path = CACHE_PATH) -> dict | None:
    """キャッシュ JSON を読み込む。なければ ``None``。"""
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def build_style_block(cache: dict | None, *, max_chars: int = 3500) -> str:
    """``STYLE_GUIDE`` 本文 + キャッシュ記事抜粋を結合した prompt 用ブロック。

    cache が None なら ``STYLE_GUIDE`` のみ返す。
    記事抜粋は ``max_chars`` を上限に、新しい順から本文を加える。
    """
    parts = [STYLE_GUIDE]
    if cache is None:
        return parts[0]

    articles = cache.get("articles") or []
    fetched_at = cache.get("fetched_at", "?")
    source_url = cache.get("source_url", "?")

    parts.append(
        f"\n【神山さん note ブログからの実例】\n"
        f"出典: {source_url}（cached {fetched_at}）\n"
    )

    used = 0
    for i, art in enumerate(articles, start=1):
        title = art.get("title", "")
        body = art.get("body", "")
        url = art.get("url", "")
        # 1 記事あたりの想定枠を残量に応じて確保
        header = f"\n--- 実例 {i}: 「{title}」 ({url}) ---\n"
        budget = max_chars - used - len(header)
        if budget <= 200:
            break
        snippet = body[:budget].rstrip()
        block = f"{header}{snippet}\n"
        parts.append(block)
        used += len(block)
        if used >= max_chars:
            break

    return "".join(parts)


def build_style_block_from_disk(*, max_chars: int = 3500) -> str:
    """ディスクからキャッシュを読み込み、整形済み文字列を返すヘルパー。"""
    cache = load_style_cache()
    return build_style_block(cache, max_chars=max_chars)
