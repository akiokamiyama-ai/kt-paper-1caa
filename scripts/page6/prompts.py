"""第6面 AI神山コラムのプロンプト定義。

miibo agent 自身に persona と stylistic guideline は既に内蔵されているため、
Tribune 側からは「今朝出会った1本」のメタ情報と JSON 出力フォーマットだけを
渡す。ここで追加の persona prompt は付けない（agent の声を二重定義しない）。
"""

from __future__ import annotations

# AI 神山に投げる発話のテンプレート。
# {title} / {source} / {description} を str.format で埋める。
AI_KAMIYAMA_PROMPT_TEMPLATE = """今朝の Tribune が出会った1本：

【タイトル】{title}
【出典】{source}
【概要】{description}

この記事を読んで、神山さんの視点で 500 字前後の一筆を書いてください。
神山さんが普段読まない領域からの出会いです。
聞き上手の眼差しで、何かが言えれば。

最後に、コラムタイトル（10〜20 字程度）も付けてください。

【出力フォーマット】
JSON で以下を返してください（前置き・後置き・コードフェンス禁止）：
{{
  "column_title": "短いコラムタイトル（10〜20 字）",
  "column_body": "500 字前後の一筆"
}}"""


# fallback 時の表示テンプレート（HTML に出力されるため display 名は「AIかみやま」）
FALLBACK_TITLE = "本日 AIかみやま休載"
FALLBACK_BODY = "本日は AIかみやまとの通信が確立できませんでした。"
