"""第5面（AI Kamiyama's Column）の生成。

C155 (Sprint 13, 2026-08-10) で「AIかみやまの一筆」100% の面に再構成した。
旧構成は上 40% がセレンディピティ記事、下 60% が一筆という 2 枠だったが、
セレンディピティ枠は第3面 6 枠目へ移設した
（``scripts/selector/serendipity.py``）。

* ``ai_kamiyama_selector`` — 一筆の論評対象記事を選ぶ。候補プールは第3面の
  確定 6 枠 + 第3面で採用されなかった評価済み上位候補（runner-up）。
  runner-up は第3面が既に採点済なので追加 LLM コストはかからない。
* ``article_summarizer``   — 参照記事の日本語サマリ（300-400 字）を
  Anthropic API で生成。一筆の隣に併載し、読者が「何への論評か」を
  紙面内で理解できるようにする。事実要約に徹し、評価・解釈は入れない
  （それは一筆の役割）。
* ``ai_kamiyama_writer``   — miibo API 経由で AIかみやまに一筆を生成依頼。
  失敗時は休載 fallback（Anthropic 代替生成は使わない、AIかみやまの声を
  真似ない設計）。
* ``prompts``              — AIかみやまへの発話テンプレート。
"""
