"""Phase 2 Sprint 3 Step C: 第5面（Leisure）の動的化サブパッケージ。

* ``leisure_recommender`` — 読書 / 音楽 / アウトドアの3領域共通の RAG +
  コラム生成（books.md / music.md / outdoor.md から記事1本選定 → LLM コラム）
* ``cooking_generator`` — 料理コラムを LLM で自律生成（RAG なし、
  cooking_history.json で30日履歴管理）
* ``prompts`` — 全領域のプロンプト定義（保守性のため一元管理）
"""
