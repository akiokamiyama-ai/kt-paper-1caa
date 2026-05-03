"""第5面（Columns & Serendipity）の動的化。

Sprint 4 layout swap で旧 page6 から移動（実装は Sprint 3 Step D）。

* ``serendipity_selector`` — 過去30日の表示履歴から最少 category を特定し
  該当領域から1記事を選定（上位5本プールからランダム）。
* ``ai_kamiyama_writer``   — miibo API 経由で AIかみやまに500字前後の一筆を
  生成依頼。失敗時は休載 fallback（Anthropic 代替生成は使わない、
  AIかみやまの声を真似ない設計）。
* ``prompts``              — AIかみやまへの発話テンプレート。
"""
