"""CSS markers + style strings for each page section.

C81 段階 3 (Sprint 9, 2026-06-13, Fable review M6 god module 分割の第三弾):
旧 ``regen_front_page_v2.py`` から CSS 定数（8 個の MARKER + CSS 文字列）を
切り出した。inject_*_css 関数は元 module に残し、本 module の定数を import
して使う。

各セクション (MASTHEAD_DATA / EDITORIAL / LINK_STYLE / PAGE_ONE / PAGE_TWO /
PAGE_FOUR / PAGE_FIVE / PAGE_SIX) は次のペア構造で定義される：

- ``<NAME>_CSS_MARKER``: idempotency 用のコメントマーカー（重複 inject 防止）
- ``<NAME>_CSS``: 実際の CSS 文字列（``{MARKER}`` を含む f-string）

各セクション CSS の意味論や Sprint 経緯は CSS 内コメントを参照。
"""

from __future__ import annotations


# ======================================================================
# MASTHEAD_DATA
# ======================================================================

MASTHEAD_DATA_CSS_MARKER = "/* === Masthead data (Sprint 5 task #2, 2026-05-04) === */"

MASTHEAD_DATA_CSS = f"""
{MASTHEAD_DATA_CSS_MARKER}
.masthead-data {{
  margin: 8px 0 16px;
  padding: 8px 0;
  border-top: 1px solid #999;
  border-bottom: 1px solid #999;
  font-family: 'Noto Serif JP', serif;
  font-size: 12px;
  text-align: center;
  color: #444;
}}
.masthead-data-row1,
.masthead-data-row2 {{
  margin: 2px 0;
  letter-spacing: 0.05em;
}}
.masthead-data .separator {{
  margin: 0 8px;
  color: #999;
}}
"""

# ======================================================================
# EDITORIAL
# ======================================================================

EDITORIAL_CSS_MARKER = "/* === Editorial postscript (Sprint 4 Phase 3) === */"

EDITORIAL_CSS = f"""
{EDITORIAL_CSS_MARKER}
/* Sprint 5 ポストモーメント (2026-05-04): 神山さんレビュー
   「6面と編集後記を分けるラインは横いっぱいに引いたほうがいい」を反映。
   旧構造では .editorial-footer に max-width: 800px が掛かり、border-top も
   800px に縛られていた。inner wrapper を新設して責務分離：
     - .editorial-footer       : 横幅 100%、border-top + 上下 padding
     - .editorial-footer-inner : max-width 800px + 中央寄せ + 左右 padding */
.editorial-footer {{
  margin-top: 32px;
  padding: 24px 0 32px;
  border-top: 2px solid #333;
  font-family: 'Noto Serif JP', serif;
  font-size: 13px;
  line-height: 1.9;
  color: #444;
}}
.editorial-footer-inner {{
  max-width: 800px;
  margin-left: auto;
  margin-right: auto;
  padding: 0 24px;
  text-align: justify;
}}
.editorial-footer .label {{
  font-size: 10px;
  letter-spacing: 0.2em;
  color: #888;
  margin-bottom: 8px;
  text-align: center;
}}
.editorial-footer .body p {{
  text-indent: 1em;
  margin: 0;
}}
.editorial-footer .signature {{
  text-align: right;
  font-style: italic;
  color: #888;
  font-size: 11px;
  margin-top: 12px;
}}
/* C69 (Sprint 9, 2026-06-09): 「コメントを書く →」CTA を 1 面右下に移設。
   旧 .editorial-footer .write-comment-cta スタイルは廃止。新位置のスタイル
   は .page page-one / page-one-v3 共通の .page-one-cta で吸収する。
   1 面 section に position:relative を付与、CTA を absolute bottom/right に
   貼り付ける。狭い画面では position:static にして overlap を避ける。 */
.page.page-one,
.page.page-one-v3 {{
  position: relative;
}}
.page .page-one-cta {{
  position: absolute;
  bottom: 14px;
  right: 18px;
  font-size: 12px;
  z-index: 2;
}}
.page .page-one-cta a {{
  color: #555;
  text-decoration: none;
  border-bottom: 1px dotted #999;
  letter-spacing: 0.02em;
}}
.page .page-one-cta a:hover {{
  color: #1a1a1a;
  border-bottom-style: solid;
}}
@media (max-width: 480px) {{
  /* スマホでは絶対配置を解除して section 末尾に普通に流す。
     固定配置だと本文と重なって読みにくい。 */
  .page .page-one-cta {{
    position: static;
    text-align: right;
    margin-top: 16px;
    padding: 0 12px;
    bottom: auto;
    right: auto;
  }}
}}
"""

# ======================================================================
# LINK_STYLE
# ======================================================================

LINK_STYLE_CSS_MARKER = "/* === Sprint 6 unified link style === */"

LINK_STYLE_CSS = f"""
{LINK_STYLE_CSS_MARKER}
a {{
  color: inherit;
  text-decoration: none;
  border-bottom: 1px dotted #888;
  padding-bottom: 1px;
}}
a:hover {{
  border-bottom-style: solid;
}}
a:visited {{
  color: inherit;
}}
"""

# ======================================================================
# PAGE_ONE
#
# C155 (Sprint 13, 2026-08-10): PAGE_ONE_CSS / PAGE_ONE_CSS_MARKER を削除。
# v2 の Page I（トップ1本 + セカンド3本、.article-title-original 等）が
# 廃止され、Page I の CSS は page1_v3.renderer.PAGE_ONE_V3_CSS が担当する。
# v2 が出す休載プレースホルダは inline style で足りるため専用 CSS を持たない。
# ======================================================================

# ======================================================================
# PAGE_TWO
# ======================================================================

PAGE_TWO_CSS_MARKER = "/* === Page II logos (2026-05-03) === */"

PAGE_TWO_CSS = f"""
{PAGE_TWO_CSS_MARKER}
/* Sprint 5 ポストモーメント (2026-05-04): ロゴを社名の上にセンター配置に変更。
   神山さんレビュー「字の上にロゴが来て、センター合わせが一番きれい」を反映。
   既存 template (archive/2026-04-25.html) の .briefing-row .company は
   text-align 未指定なので、ここで center 指定して上書き。 */
.briefing-row .company {{
  text-align: center;
}}
.briefing-row .company .company-logo {{
  display: block;
  height: 28px;
  width: auto;
  margin: 0 auto 4px;
  filter: grayscale(100%) contrast(1.3);  /* pattern-3 採用 (2026-05-03) */
}}
.briefing-row .company .company-name {{
  display: block;
}}

/* C155 (Sprint 13, 2026-08-10): Today's Headlines (.todays-headlines 一式) の
   CSS を削除。第2面は 3 社ブリーフィングのみになった。 */
"""

# ======================================================================
# PAGE_FOUR
# ======================================================================

PAGE_FOUR_CSS_MARKER = "/* === Page IV (Sprint 3 Step B) === */"

PAGE_FOUR_CSS = f"""
{PAGE_FOUR_CSS_MARKER}
.page-four-grid {{
  display: grid;
  grid-template-columns: 55% 45%;
  gap: 24px;
  padding: 16px 24px;
}}
.concept-column {{
  border-right: 1px solid #ddd;
  padding-right: 24px;
}}
.concept-title {{
  font-family: 'Noto Serif JP', 'Old Standard TT', serif;
  font-size: 28px;
  font-weight: 700;
  margin: 8px 0 4px;
  line-height: 1.3;
}}
.concept-en {{
  display: block;
  font-size: 14px;
  font-weight: 400;
  color: #666;
  font-style: italic;
  margin-top: 2px;
}}
.concept-meta {{
  font-size: 12px;
  color: #888;
  margin-bottom: 16px;
  padding-bottom: 12px;
  border-bottom: 1px dotted #ccc;
}}
.concept-meta .domain {{ margin-right: 12px; font-weight: 600; }}
.concept-meta .thinkers {{ font-style: italic; }}
.concept-essay p {{
  font-family: 'Noto Serif JP', 'Old Standard TT', serif;
  font-size: 15px;
  line-height: 1.9;
  text-align: justify;
  text-indent: 1em;
}}
/* C155 (Sprint 13, 2026-08-10): 学術ニュース枠 (.academic-column) を廃止。
   概念コラム 1 本だけの面になったので、2 カラム grid を単一カラムに切替える。
   .page-four-single が付いたときは concept-column の縦罫も外す。 */
.page-four-grid.page-four-single {{
  grid-template-columns: 1fr;
  max-width: 760px;
  margin: 0 auto;
}}
.page-four-single .concept-column {{
  border-right: none;
  padding-right: 0;
}}
/* Sprint 8 C41 (2026-05-28): iPad / iPhone レスポンシブ。 */
@media (max-width: 834px) {{
  .page-four-grid {{
    grid-template-columns: 1fr;
    gap: 20px;
    padding: 12px 16px;
  }}
  .concept-column {{
    border-right: none;
    border-bottom: 1px solid #ddd;
    padding-right: 0;
    padding-bottom: 20px;
  }}
}}
@media (max-width: 480px) {{
  .page-four-grid {{
    padding: 10px 12px;
    gap: 16px;
  }}
  .concept-title {{ font-size: 24px; }}
}}
"""

# ======================================================================
# PAGE_FIVE
# ======================================================================

PAGE_FIVE_CSS_MARKER = "/* === Page V (Sprint 4 layout swap, was Sprint 3 Step D) === */"

PAGE_FIVE_CSS = f"""
{PAGE_FIVE_CSS_MARKER}
/* C155 (Sprint 13, 2026-08-10): 第5面を「AIかみやまの一筆」100% に。
   旧構成は上 40% セレンディピティ / 下 60% 一筆の固定比 grid だった。
   セレンディピティは第3面へ移設し、上段は「一筆が読んだ記事」の
   参照サマリ（300-400 字）に置き換わる。固定比をやめて内容に応じた
   auto 送りにし、一筆本文が主役として面を占めるようにする。 */
.page-five-content {{
  display: grid;
  grid-template-rows: auto 1fr;
  padding: 16px 24px;
}}
.reference-article {{
  padding-bottom: 24px;
  margin-bottom: 24px;
  border-bottom: 1px solid #ccc;
}}
.reference-article .kicker {{
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.1em;
  color: #666;
  text-transform: uppercase;
  margin-bottom: 8px;
}}
.reference-article .article-title {{
  font-family: 'Noto Serif JP', 'Old Standard TT', serif;
  font-size: 18px;
  font-weight: 700;
  line-height: 1.5;
  margin: 0 0 10px;
}}
.reference-article .reference-summary {{
  font-family: 'Noto Serif JP', 'Old Standard TT', serif;
  font-size: 14px;
  line-height: 1.8;
  color: #333;
  margin-bottom: 8px;
}}
.reference-article .reference-byline {{
  font-size: 11px;
  color: #888;
  border-top: 1px dotted #ccc;
  padding-top: 6px;
}}
.ai-kamiyama-column .kicker {{
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.1em;
  color: #666;
  text-transform: uppercase;
  margin-bottom: 8px;
}}
/* Sprint 7 Phase 1 Step 2 (2026-05-19): AIかみやま 対象記事の参照行。
   下部 column の最初に「対象記事：title （source）」を 1 行表示し、
   読者が「AIかみやま が何を論評しているか」を一目で把握できるようにする。 */
.ai-kamiyama-column .ai-source-ref {{
  font-size: 12px;
  color: #555;
  margin: 0 0 12px;
  padding-bottom: 8px;
  border-bottom: 1px dotted #ccc;
  line-height: 1.5;
}}
.ai-kamiyama-column .ai-source-ref a {{
  color: var(--ink);
  text-decoration: none;
  border-bottom: 1px dotted var(--ink-soft);
}}
.ai-kamiyama-column .ai-source-ref a:hover {{
  border-bottom-style: solid;
}}
/* Sprint 8 (2026-05-20, C16): 対象記事の概要。独立選定で他面に
   乗らないため、引用風 box-out で「何への論評か」を視覚的に提示。 */
.ai-kamiyama-column .ai-article-summary {{
  font-size: 13px;
  color: #555;
  line-height: 1.7;
  margin: 8px 0 16px;
  padding: 8px 12px;
  background: rgba(0, 0, 0, 0.02);
  border-left: 2px solid #ccc;
}}
.ai-kamiyama-column .column-title {{
  font-family: 'Noto Serif JP', 'Old Standard TT', serif;
  font-size: 22px;
  font-weight: 700;
  line-height: 1.4;
  margin: 0 0 16px;
}}
.ai-kamiyama-column .column-body p {{
  font-family: 'Noto Serif JP', 'Old Standard TT', serif;
  font-size: 15px;
  line-height: 1.9;
  text-align: justify;
  text-indent: 1em;
  margin-bottom: 12px;
}}
.ai-kamiyama-column .ai-byline {{
  font-size: 11px;
  color: #888;
  text-align: right;
  font-style: italic;
  margin-top: 12px;
}}
.page-five-placeholder {{
  text-align: center;
  padding: 60px 24px;
  color: #888;
  font-style: italic;
}}
/* Sprint 8 C41 (2026-05-28): iPad / iPhone レスポンシブ。
   AIかみやま column の文章が枠からはみ出る問題に対し、
   (1) overflow-wrap で長語を折り返し、
   (2) iPad / iPhone では padding / 行間を緩めて余裕を持たせる。 */
.page-five-content,
.reference-article,
.ai-kamiyama-column {{
  min-width: 0;
  overflow-wrap: break-word;
  word-break: normal;
}}
.ai-kamiyama-column .column-body p,
.ai-kamiyama-column .column-title,
.ai-kamiyama-column .ai-source-ref,
.ai-kamiyama-column .ai-article-summary,
.reference-article .article-title,
.reference-article .reference-summary {{
  overflow-wrap: break-word;
}}
@media (max-width: 834px) {{
  .page-five-content {{
    grid-template-rows: auto auto;
    padding: 16px 18px;
    row-gap: 12px;
  }}
  .reference-article {{
    padding-bottom: 18px;
    margin-bottom: 18px;
  }}
  .ai-kamiyama-column .column-title {{ font-size: 20px; }}
  .ai-kamiyama-column .column-body p {{
    font-size: 14px;
    line-height: 1.85;
  }}
  .ai-kamiyama-column .ai-article-summary {{
    padding: 10px 12px;
    font-size: 13px;
  }}
}}
@media (max-width: 480px) {{
  .page-five-content {{
    padding: 12px 14px;
    row-gap: 10px;
  }}
  .ai-kamiyama-column .column-title {{
    font-size: 18px;
    line-height: 1.4;
  }}
  .ai-kamiyama-column .column-body p {{
    font-size: 14px;
    text-indent: 1em;
  }}
  .ai-kamiyama-column .ai-article-summary {{
    padding: 8px 10px;
    font-size: 12.5px;
  }}
  .reference-article .article-title {{ font-size: 16px; }}
  .reference-article .reference-summary {{ font-size: 13px; }}
}}
"""

# ======================================================================
# PAGE_SIX
# ======================================================================

PAGE_SIX_CSS_MARKER = "/* === Page VI (Sprint 4 layout swap, was Sprint 3 Step C) === */"

PAGE_SIX_CSS = f"""
{PAGE_SIX_CSS_MARKER}
.page-six-grid-v2 {{
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 0;
  padding: 16px 24px;
}}
.leisure-column-v2 {{
  padding: 0 16px;
  border-right: 1px solid #ccc;
}}
.leisure-column-v2:last-child {{ border-right: none; }}
.leisure-column-v2:first-child {{ padding-left: 0; }}
.leisure-column-v2 .kicker {{
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.1em;
  color: #666;
  text-transform: uppercase;
  margin-bottom: 8px;
}}
.leisure-column-v2 .column-title {{
  font-family: 'Noto Serif JP', 'Old Standard TT', serif;
  font-size: 17px;
  font-weight: 700;
  line-height: 1.4;
  margin: 0 0 12px;
}}
/* Sprint 5 task #4 (2026-05-04): focus-work（題材表記）のスタイル。
   books / music / outdoor で column-title の直下に出る。cooking 用の
   .dish-name とは別スタイルで、italic のメタ情報感を出す。 */
.leisure-column-v2 .focus-work {{
  font-family: 'Noto Serif JP', serif;
  font-size: 12px;
  font-style: italic;
  color: #666;
  margin: 4px 0 8px;
  padding-left: 4px;
  border-left: 2px solid #999;
  line-height: 1.5;
}}
.leisure-column-v2 .column-body p {{
  font-family: 'Noto Serif JP', 'Old Standard TT', serif;
  font-size: 13px;
  line-height: 1.8;
  text-align: justify;
  margin-bottom: 8px;
}}
.leisure-column-v2 .byline-v2 {{
  font-size: 10px;
  color: #888;
  margin-top: 8px;
  border-top: 1px dotted #ccc;
  padding-top: 6px;
}}
.cooking-column-v2 .dish-name {{
  font-size: 14px;
  font-weight: 600;
  color: #333;
  margin: 0 0 4px;
}}
.cooking-column-v2 .ingredients {{
  font-size: 12px;
  color: #555;
  font-style: italic;
  margin-bottom: 10px;
  padding: 6px 8px;
  background: #f8f5f0;
  border-left: 2px solid #c0a060;
}}
/* Sprint 8 C41 (2026-05-28): iPad / iPhone レスポンシブ。
   4 列 → iPad は 2 列、iPhone 13 mini は 1 列に折り畳む。 */
@media (max-width: 834px) {{
  .page-six-grid-v2 {{
    grid-template-columns: repeat(2, 1fr);
    row-gap: 24px;
    padding: 12px 16px;
  }}
  .leisure-column-v2 {{
    padding: 0 12px;
    border-right: 1px solid #ccc;
  }}
  .leisure-column-v2:nth-child(odd) {{ padding-left: 0; }}
  .leisure-column-v2:nth-child(even) {{
    padding-right: 0;
    border-right: none;
  }}
  .leisure-column-v2:nth-child(n+3) {{
    padding-top: 20px;
    border-top: 1px dotted #ccc;
  }}
}}
@media (max-width: 480px) {{
  .page-six-grid-v2 {{
    grid-template-columns: 1fr;
    row-gap: 20px;
    padding: 10px 14px;
  }}
  .leisure-column-v2,
  .leisure-column-v2:nth-child(odd),
  .leisure-column-v2:nth-child(even),
  .leisure-column-v2:nth-child(n+3) {{
    padding: 16px 0 0;
    border-right: none;
    border-top: 1px dotted #ccc;
  }}
  .leisure-column-v2:first-child {{
    padding-top: 0;
    border-top: none;
  }}
}}
"""
