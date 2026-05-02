"""Phase 2 Sprint 3 Step D: 第6面（Columns & Serendipity）の動的化。

* ``serendipity_selector`` — 過去30日の表示履歴から最少 category を特定し
  該当領域から1記事を選定（上位5本プールからランダム）。
* ``ai_kamiyama_writer``   — miibo API 経由で AI 神山に300字の一筆を生成
  依頼。失敗時は休載 fallback（Anthropic 代替生成は使わない、AI神山の声を真似ない設計）。
* ``prompts``              — AI神山への発話テンプレート。
"""
