"""Tribune note generation — 1 週間の論考＋コメントを集約して note 公開用の草稿
Markdown を生成するパッケージ。

C38b (Sprint 9, 2026-06-09):
- 入力: archive/{date}.html の page IV 概念エッセイ + data/comments/{date}.md
- LLM: Claude Sonnet 4.6（既存 scripts.lib.llm を再利用）
- 出力: data/notes/{label}.md（neat-published Markdown 草稿、3000-5000字）
- 起動: ``python -m scripts.notes.generate --start YYYY-MM-DD --end YYYY-MM-DD``

詳細は ``scripts/notes/generate.py`` の docstring を参照。
"""
