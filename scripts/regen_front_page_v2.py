#!/usr/bin/env python3
"""Regenerate Page I (front page) with the Phase 2 美意識 selection pipeline.

Pipeline differs from ``regen_front_page.py`` (v1):

* Multi-source candidate fetch (BBC Business + The Economist + Foresight)
  via the existing fetch infrastructure.
* Stage 1 (mechanical filter) → Stage 2 (LLM batch evaluation, Sonnet 4.6
  with prompt caching) → Stage 3 (final_score integration) per
  ``docs/aesthetics_design_v1.md`` §4.1.
* Top 4 by ``final_score`` are selected — no AI keyword promote, no
  explainer skip.
* Bodies are not scraped; the rendered Page I uses the (translated)
  description only. Sprint 2 may revisit per-source body extraction.

Output goes to ``archive/YYYY-MM-DD.html`` (a fresh file derived from the
existing ``2026-04-25.html`` template with date strings updated). The
template itself and ``archive/2026-04-25.html`` are never modified.
``index.html`` is only touched if ``--update-index`` is passed.

CLI::

    python3 -m scripts.regen_front_page_v2                  # generate today
    python3 -m scripts.regen_front_page_v2 --dry-run        # preview only
    python3 -m scripts.regen_front_page_v2 --date 2026-04-29
    python3 -m scripts.regen_front_page_v2 --update-index   # also update redirect
"""

from __future__ import annotations
from .lib.jst import jst_today

import argparse
import html
import re
import sys
from datetime import date, datetime, timezone, timedelta
from pathlib import Path

from .render import replace_page_one
from .selector.dedup_filter import (
    filter_recently_displayed,
    load_recently_displayed_urls,
    write_displayed_urls_log,
)
from .selector.page2 import (
    COMPANY_KEYS as PAGE2_COMPANY_ORDER,
    SHORT_TO_CATEGORY as PAGE2_SHORT_TO_CATEGORY,
    default_fetcher as page2_default_fetcher,
    prepare_shared_cross_industry_pool,
    run_page2_pipeline,
)
from .selector.page3 import (
    DISPLAY_SLOTS as PAGE3_DISPLAY_SLOTS,
    REGION_DISPLAY_NAMES as PAGE3_REGION_DISPLAY_NAMES,
    SERENDIPITY_SLOT as PAGE3_SERENDIPITY_SLOT,
    _generate_kicker as _page3_generate_kicker,
    _is_japanese_source as _page3_is_japanese_source,
    run_page3_pipeline,
)
from .editorial import context_builder as editorial_context
from .editorial import editorial_writer
from .header import header_builder as header_module
from .page4 import concept_selector as page4_concept_selector
from .page4 import concept_writer as page4_concept_writer
from .page4 import related_concepts as page4_related
from .page5 import ai_kamiyama_writer as page5_ai_kamiyama
from .page6 import cooking_generator as page6_cooking
from .page6 import leisure_recommender as page6_leisure

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ARCHIVE_DIR = PROJECT_ROOT / "archive"
TEMPLATE_PATH = ARCHIVE_DIR / "2026-04-25.html"
INDEX_HTML = PROJECT_ROOT / "index.html"

# C155 (Sprint 13, 2026-08-10): SOURCE_NAME_FILTERS の re-export を廃止。
# v2 の Page I fetch（唯一の利用者）が消えたため。定義自体は
# ``scripts/source_allowlist.py`` に残り、``scripts/source_layers.py`` の
# 層 1 定義から参照され続ける。

# C81 段階 4 (Sprint 9, 2026-06-13, Fable review M6): 翻訳判定・ヘルパーは
# ``scripts/translation_helpers.py`` に移動。旧 import 互換のため re-export を残す。
from .translation_helpers import (  # noqa: F401  re-export
    is_japanese_article as _is_japanese_article,
    translate_for_render,
)

# Sprint 2 Step B 期間中の page2.run_page2_pipeline 呼び出し時の運用 threshold。
# scripts/selector/page2.py の DEFAULT_THRESHOLD = 40.0 を caller 側で
# override する形（page2.py のモジュール定数は不変）。
PAGE2_THRESHOLD = 35.0

# Sprint 2 Step D: 重複排除レイヤー。displayed_urls_*.json を遡及参照して
# 過去 N 日に「実際に紙面で表示した」記事を翌朝以降の選定から除外する。
PAGE1_DEDUP_DAYS = 7
PAGE2_DEDUP_DAYS = 3
# C168 (Sprint 13, 2026-08-17): 第5面 AIかみやま 参照記事の自己 dedup 窓。
# 5 面は長らく唯一 dedup を持たない面だった（C40 が「他面 dedup に相乗りする
# から不要」と設計したが、C167 調査で全期間 6 件の日跨ぎ重複が判明し前提が
# 崩れた）。7 日にした理由は、候補の供給元が 3 面 runner-up で 3 面の窓が
# 7 日だから——「3 面に 7 日出ていない & 5 面に 7 日出ていない」で意味が揃う。
# 実測では 30 日窓でも残候補 17-20 件（top_n=5 に必要な 5 件を大きく上回る）
# ため枯渇リスクは実質ゼロ。強めたければこの 1 行を伸ばせばよい。
# C190 (2026-08-31): 7 → 30。C168 が 7 にしたのは「3 面の dedup 窓が 7 日だから
# 意味が揃う」という概念的な対称性が理由だったが、5 面の候補プール（3 面
# runner-up）は 3 面より狭いため同じ窓では足りなかった。実際、C168 以降の重複
# 2 件はどちらも **ちょうど 9 日間隔**で、7 日窓のすぐ外を通っていた:
#
#   2026-08-26 ← 08-17 (9 日)  thepointmag /we-were-the-99-percent/（3 回目）
#   2026-08-31 ← 08-22 (9 日)  publicbooks /literature-in-the-time-of-suicide/
#
# 30 日窓の安全性は C168 が既に実測していた（残候補 17-20 件、必要なのは
# top_n=5）。当時のコミットに「強めたければ定数 1 行を伸ばせばよい」とある。
PAGE5_DEDUP_DAYS = 30

# C190: 未出優先（段 2）の判定に使う全期間の既出集合を取るための遡り日数。
# 運用開始 2026-04-25 を余裕をもってカバーする。log が無い日は単に skip される。
PAGE5_UNSEEN_LOOKBACK_DAYS = 400

# 逆引き：companies.md の Source.category → page2 短縮キー
PAGE2_CATEGORY_TO_KEY: dict[str, str] = {
    cat: key for key, cat in PAGE2_SHORT_TO_CATEGORY.items()
}

# 第2面の3社表示メタデータ：display_name + 業種ラベル。
# archive/2026-04-25.html Page II の <div class="company"> 構造を踏襲。
COMPANY_DISPLAY_META: dict[str, tuple[str, str]] = {
    "cocolomi":     ("Cocolomi",     "生成AI導入支援"),
    "human_energy": ("Human Energy", "企業向け研修"),
    "web_repo":     ("Web-Repo",     "フランチャイズ業界"),
}

# C155 (Sprint 13, 2026-08-10): 以下は v2 Page I パイプラインと共に廃止。
#   * N_TOP / N_SECONDARIES / PER_SOURCE_LIMIT — トップ1+セカンド3 の紙面構成
#   * scripts/page1_penalty.py — Page I 限定の source soft penalty
#     (Foresight / 新潮 QUE の頻出抑制)。Page I が週次 essay になり
#     日次のソース選定自体が無くなったため機構ごと不要になった。

# C81 段階 3 (Sprint 9, 2026-06-13, Fable review M6): CSS 定数 (MARKER + CSS)
# は ``scripts/page_styles.py`` に集約。inject_*_css 関数は本 module に残り、
# page_styles の定数を import して使う。旧 import path 維持のため re-export。
from .page_styles import (  # noqa: F401  re-export
    EDITORIAL_CSS,
    EDITORIAL_CSS_MARKER,
    LINK_STYLE_CSS,
    LINK_STYLE_CSS_MARKER,
    MASTHEAD_DATA_CSS,
    MASTHEAD_DATA_CSS_MARKER,
    PAGE_FIVE_CSS,
    PAGE_FIVE_CSS_MARKER,
    PAGE_FOUR_CSS,
    PAGE_FOUR_CSS_MARKER,
    PAGE_SIX_CSS,
    PAGE_SIX_CSS_MARKER,
    PAGE_TWO_CSS,
    PAGE_TWO_CSS_MARKER,
)

# Source-name prefix → kicker ja text.
KICKER_PREFIXES: tuple[tuple[str, str], ...] = (
    ("BBC Business",  "BBC ビジネス"),
    ("The Economist", "The Economist"),
    ("Foresight",     "Foresight・国際情勢"),
)
DEFAULT_KICKER = "本紙編集部"

# Footer / template substitution patterns.
_DOW_JA = ("月", "火", "水", "木", "金", "土", "日")
_DOW_EN = (
    "Monday", "Tuesday", "Wednesday",
    "Thursday", "Friday", "Saturday", "Sunday",
)


_HTML_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")


# ---------------------------------------------------------------------------
# Article preparation
# ---------------------------------------------------------------------------

# pub_date は ISO 8601 文字列（Stage 1 / page2 が Article.pub_date.isoformat()
# として article dict に乗せる）。タイムゾーンは JST 換算してから日付部分を
# 取り出す（UTC で 22:00 の記事は JST で翌日 7:00 になり、表示日付が翌日に
# シフトする）。
_JST = timezone(timedelta(hours=9))


def _format_publish_date_ja(iso_date_str: str | None) -> str:
    """Convert ISO 8601 date string to "YYYY年M月D日" (JST-converted).

    Returns an empty string when input is None, malformed, or unparseable —
    so callers can ``f"{byline_base}{maybe_date}"`` without conditional logic.
    Accepts both full datetimes (``"2026-04-28T10:30:00+00:00"``) and date-
    only strings (``"2026-04-28"``).
    """
    if not iso_date_str:
        return ""
    try:
        # datetime.fromisoformat (Python 3.11+) accepts "Z" suffix and most
        # standard ISO 8601 forms.
        dt = datetime.fromisoformat(iso_date_str)
    except (TypeError, ValueError):
        # Try date-only "YYYY-MM-DD".
        try:
            dt = datetime.fromisoformat(f"{iso_date_str}T00:00:00")
        except (TypeError, ValueError):
            return ""
    # Naive datetimes: assume UTC (RSS feeds typically publish in UTC or
    # encode timezone explicitly; truly naive timestamps are ambiguous).
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt_jst = dt.astimezone(_JST)
    return f"{dt_jst.year}年{dt_jst.month}月{dt_jst.day}日"


def inject_masthead_data_css(html_text: str) -> str:
    """Idempotently inject masthead-data CSS just before </style>."""
    if MASTHEAD_DATA_CSS_MARKER in html_text:
        return html_text
    end_style_idx = html_text.rfind("</style>")
    if end_style_idx < 0:
        head_close = html_text.find("</head>")
        if head_close < 0:
            return html_text
        injected = f"<style>\n{MASTHEAD_DATA_CSS}\n</style>\n"
        return html_text[:head_close] + injected + html_text[head_close:]
    return html_text[:end_style_idx] + MASTHEAD_DATA_CSS + html_text[end_style_idx:]


def replace_strip_with_masthead_data(html_text: str, new_block: str) -> str:
    """Replace ``<div class="strip">...</div>`` with ``new_block``.

    The static template's strip is a single non-nested div. We find the
    opening tag and the next ``</div>`` after it. Idempotent on empty
    new_block (returns html_text unchanged) and on missing strip (template
    might have been edited).
    """
    if not new_block:
        return html_text
    start_marker = '<div class="strip">'
    pos = html_text.find(start_marker)
    if pos < 0:
        # No strip in template (already replaced or template changed) — defensive
        # fallback: insert masthead-data immediately after </header> instead.
        header_close = html_text.find("</header>")
        if header_close < 0:
            return html_text
        insert_at = header_close + len("</header>")
        return html_text[:insert_at] + "\n\n  " + new_block + html_text[insert_at:]
    end = html_text.find("</div>", pos)
    if end < 0:
        return html_text
    end += len("</div>")
    return html_text[:pos] + new_block.rstrip() + html_text[end:]


# Sprint 4 Phase 3 (2026-05-03): Tribune 編集後記の CSS。第6面と colophon の
# 間に挟まれる。is_fallback=True 時は HTML 自体が出ないため、CSS は常に
# inject されるが効くのは編集後記が描画された日のみ。


def inject_editorial_css(html_text: str) -> str:
    """Idempotently inject the editorial-footer CSS just before </style>."""
    if EDITORIAL_CSS_MARKER in html_text:
        return html_text
    end_style_idx = html_text.rfind("</style>")
    if end_style_idx < 0:
        head_close = html_text.find("</head>")
        if head_close < 0:
            return html_text
        injected = f"<style>\n{EDITORIAL_CSS}\n</style>\n"
        return html_text[:head_close] + injected + html_text[head_close:]
    return html_text[:end_style_idx] + EDITORIAL_CSS + html_text[end_style_idx:]


# Sprint 6 (2026-05-03): 全面共通のリンクスタイル統一。color: inherit + dotted
# underline + hover で solid。新聞らしい硬質な見た目を保つ。


def inject_link_style_css(html_text: str) -> str:
    """Idempotently inject the unified link style CSS just before </style>."""
    if LINK_STYLE_CSS_MARKER in html_text:
        return html_text
    end_style_idx = html_text.rfind("</style>")
    if end_style_idx < 0:
        head_close = html_text.find("</head>")
        if head_close < 0:
            return html_text
        injected = f"<style>\n{LINK_STYLE_CSS}\n</style>\n"
        return html_text[:head_close] + injected + html_text[head_close:]
    return html_text[:end_style_idx] + LINK_STYLE_CSS + html_text[end_style_idx:]


def _esc(s: str) -> str:
    return html.escape(s or "")


# ---------------------------------------------------------------------------
# Rendering — Page I placeholder (C155, Sprint 13, 2026-08-10)
# ---------------------------------------------------------------------------


def build_page_one_placeholder(*, target_date: date) -> str:
    """v3 が swap する対象の ``page-one`` marker section を返す.

    C155 で v2 の Page I 生成（トップ1本 + セカンド3本）を廃止した。Page I の
    中身は ``regen_front_page_v3`` が ``data/monthly_pivotal.json`` の週次
    主軸記事から essay を組んで surgical swap する。

    本関数の出力は二つの役割を持つ：

    1. **swap ターゲット** — ``regen_front_page_v3._swap_page_one`` は
       ``<section class="page page-one">`` を文字列検索して置換するため、
       この marker が archive HTML に必ず 1 個存在する必要がある。
    2. **フェイルセーフ表示** — 月次選定が未投入の週、または v3 が例外を
       吐いた日は、この内容がそのまま紙面に残る。旧実装ではテンプレートの
       2026-04-25 合宿ダミー記事が露出する危険があったが、明示的な休載
       通知に置き換えることで「古い記事が本日の紙面に出る」事故を防ぐ。
    """
    date_label = _esc(target_date.isoformat())
    return f"""<section class="page page-one">
    <div class="page-banner"><span class="pg-num">— Page I —</span> Essay &amp; Pivotal · A Week with One Question</div>

    <div class="page-one-placeholder" lang="ja" data-date="{date_label}"
         style="padding: 48px 24px; text-align: center; color: #666; font-style: italic;">
      <p>本日の第1面は休載です。</p>
      <p>今週の主軸記事が未登録のため、論考を生成できませんでした。</p>
    </div>
  </section>"""


# ---------------------------------------------------------------------------
# Rendering — Page II ("社長の朝会")
# ---------------------------------------------------------------------------

# 第2面 各社ロゴ（assets/logos/ 配置、archive/ から相対参照で ../assets/logos/）。
# default は grayscale 100%。神山さん帰宅後の目視で別パターンに切替可能。
COMPANY_LOGOS: dict[str, str] = {
    "cocolomi":     "../assets/logos/cocolomi.svg",
    "human_energy": "../assets/logos/HE.png",
    "web_repo":     "../assets/logos/web-repo.png",
}

# 第2面 ロゴ用 CSS。inject_page_two_css で </style> 直前に挿入。


def inject_page_two_css(html_text: str) -> str:
    """Idempotently inject Page II logo CSS just before the closing </style> tag.

    Skipped if the marker comment already present (safe re-runs).
    """
    if PAGE_TWO_CSS_MARKER in html_text:
        return html_text
    end_style_idx = html_text.rfind("</style>")
    if end_style_idx < 0:
        head_close = html_text.find("</head>")
        if head_close < 0:
            return html_text
        injected = f"<style>\n{PAGE_TWO_CSS}\n</style>\n"
        return html_text[:head_close] + injected + html_text[head_close:]
    return html_text[:end_style_idx] + PAGE_TWO_CSS + html_text[end_style_idx:]


def _company_logo_html(company_key: str) -> str:
    """<img> tag for a company's logo, or empty string if no logo registered."""
    src = COMPANY_LOGOS.get(company_key)
    if not src:
        return ""
    display_name, _ = COMPANY_DISPLAY_META.get(company_key, ("", ""))
    alt = f"{display_name} logo" if display_name else "company logo"
    return f'<img class="company-logo" src="{_esc(src)}" alt="{_esc(alt)}" />'


def _kicker_for_page2(source_name: str | None) -> str:
    """Return a clean kicker label for Page II briefing rows.

    Strips parenthetical metadata (e.g. ``"Foresight（新潮社）"`` →
    ``"Foresight"``) so the kicker reads cleanly. Sprint 3 で topical kicker
    生成（``"経産省・導入ガイドライン"`` 形式）を検討した場合は別 LLM call
    が必要だが、Step B は source-name ベースで済ませる。
    """
    if not source_name:
        return "本紙編集部"
    name = re.sub(r"[（(][^）)]*[）)]", "", source_name).strip()
    return name or "本紙編集部"


def _byline_for_page2(source_name: str | None) -> str:
    if not source_name:
        return "本紙編集部"
    name = re.sub(r"[（(][^）)]*[）)]", "", source_name).strip()
    return f"本紙編集部　{name}より構成" if name else "本紙編集部"


def _render_briefing_row(company_key: str, sel) -> str:
    """Render one company's <div class="briefing-row"> block.

    Two modes:
    * Selected: full row with kicker / headline / description / Editor's Note
      containing the morning question.
    * No article (sel.article is None or sel.morning_question is None):
      minimal placeholder per Sprint 2 Step B 設計（神山さん指定の最小形式）.
    """
    display_name, biz_label = COMPANY_DISPLAY_META[company_key]
    logo_html = _company_logo_html(company_key)

    # 該当なし: minimal placeholder.
    if sel.article is None or sel.morning_question is None:
        return f"""
    <div class="briefing-row" lang="ja">
      <div class="company">
        {logo_html}
        <div class="company-name">{_esc(display_name)}</div>
        <span class="jp">{_esc(biz_label)}</span>
      </div>
      <div class="story">
        <h4 class="headline-m" style="font-style: italic; color: #666;">本日休載</h4>
      </div>
    </div>""".rstrip()

    article = sel.article
    title_ja = article.get("title_ja") or article.get("title", "")
    desc_ja = article.get("desc_ja") or article.get("description", "")
    source_name = article.get("source_name", "")
    url = article.get("url", "")
    kicker = _kicker_for_page2(source_name)
    byline = _byline_for_page2(source_name)
    date_label = _format_publish_date_ja(article.get("pub_date"))
    if date_label:
        byline = f"{byline} · {date_label}"
    question = sel.morning_question

    return f"""
    <div class="briefing-row" lang="ja">
      <div class="company">
        {logo_html}
        <div class="company-name">{_esc(display_name)}</div>
        <span class="jp">{_esc(biz_label)}</span>
      </div>
      <div class="story">
        <div class="kicker">{_esc(kicker)}</div>
        <h4 class="headline-m"><a href="{_esc(url)}" target="_blank" rel="noopener noreferrer">{_esc(title_ja)}</a></h4>
        <p class="byline">{_esc(byline)}</p>
        <p>{_esc(desc_ja)}</p>
      </div>
      <div class="insight">
        <span class="label">Editor's Note · 社長への朝の覚え書き</span>
        <p><strong>今朝の問い：</strong>{_esc(question)}</p>
      </div>
    </div>""".rstrip()


def build_page_two_v2(selections: dict) -> str:
    """Assemble the full Page II <section> block from page2 pipeline selections.

    ``selections`` is the ``Page2Result.selections`` dict mapping
    ``company_key`` (cocolomi / human_energy / web_repo) → ``CompanySelection``.
    Order is fixed (Cocolomi → Human Energy → Web-Repo) per the inaugural
    issue's Page II layout.

    C155 (Sprint 13, 2026-08-10): Today's Headlines (下段 3 本) を廃止し、
    3 社ブリーフィングのみの面に戻した。Sprint 7 Phase 2 Step 2 で追加した
    ``headlines`` 引数も削除。
    """
    rows: list[str] = []
    # COMPANY_KEYS は page2.py から import 済（cocolomi → human_energy → web_repo）
    for company_key in PAGE2_COMPANY_ORDER:
        sel = selections.get(company_key)
        if sel is None:
            # Defensive: synth a stub "no article" CompanySelection.
            from .selector.page2 import CompanySelection
            sel = CompanySelection(
                company_key=company_key, article=None,
                page2_final_score=None, morning_question=None,
                stage_used="none", threshold_passed=False,
                fallback_reason="page2_pipeline returned no entry for this company",
            )
        rows.append(_render_briefing_row(company_key, sel))

    rows_html = "\n".join(rows)
    return f"""<section class="page page-two">
    <div class="page-banner"><span class="pg-num">— Page II —</span> The President's Morning Briefing · Three Companies, One Desk</div>

    <p class="deck" lang="ja" style="text-align:center; margin-bottom:18px;">
      Cocolomi・Human Energy・Web-Repo3社の事業文脈に関わる今朝の話題を、各社につき1本——朝の経営判断のための短い問いを添えて。
    </p>
{rows_html}
  </section>"""


def replace_page_two(html_text: str, new_page_html: str) -> str:
    """Surgical replace for Page II, parallel to ``render.replace_page_one``."""
    start_marker = '<section class="page page-two">'
    if html_text.count(start_marker) != 1:
        raise RuntimeError(
            f"Expected 1 page-two section, found {html_text.count(start_marker)}"
        )
    start = html_text.find(start_marker)
    end = html_text.find("</section>", start)
    if end == -1:
        raise RuntimeError("Page Two section end not found")
    end += len("</section>")
    return html_text[:start] + new_page_html + html_text[end:]


# ---------------------------------------------------------------------------
# Rendering — Page III ("General News")
# ---------------------------------------------------------------------------

# C164 (Sprint 13, 2026-08-15): 第3面 item 本文の文字数上限。
#
# 3 面は運用開始（2026-04-25）以来 **一度も truncate していなかった**。通常の
# RSS description は 800 字以内に収まるため顕在化していなかったが、8/16 紙面で
# Atlas Obscura のリスト記事（"19 Creepy Catacombs Around the World"）が
# **17,179 字**そのまま流し込まれ、3 面のグリッドが崩れた。
#
# 旧第5面のセレンディピティ枠は 300 字 truncate していたが、C155 で枠を 3 面へ
# 移した際、3 面の renderer には truncate が無かったため制限が失われた。
# SER 枠固有ではなく **3 面 6 枠すべてに上限が無い**のが真因。
#
# 実測分布（archive 109 日分・593 item）:
#     p50=174  p75=299  p90=458  p95=675  p99=802  max=17,179
#     1000 字超は 1 件のみ（今回の Atlas Obscura）
#
# 400 字は p90 相当。外れ値を確実に潰しつつ、既存 item の 9 割は無改変で残る。
# 3 列グリッドでセル高が揃う実用的な上限でもある。旧 5 面準拠の 300 字にすると
# 既存の 24% が truncate されて紙面の見た目が大きく変わるため採らなかった。
PAGE3_DESC_MAX_CHARS = 400


def _render_page3_item(article: dict, region: str) -> str:
    """Render one <div class="item"> for Page III.

    Uses the article's element language for the ``lang`` attribute. Source
    text is kept as-is — no translation runs on Page III articles per
    page3_design_v1.md §13 Q5.

    Sprint 3 Step A 改善（2026-05-01）：本文の直後に「出典：source · 日付」
    の byline を追加。pub_date が無いソースは日付省略。why_important.py
    と同じ ``_format_publish_date_ja()`` を再利用。
    """
    is_ja = _page3_is_japanese_source(article.get("source_name"))
    lang_attr = ' lang="ja"' if is_ja else ''
    kicker = _page3_generate_kicker(article, region)
    title = article.get("title") or ""
    # C164: 6 枠すべてに同じ上限をかける（SER 枠も他 5 枠と同格に扱う）。
    # _truncate_to_chars は文末（。．.）で切るので不自然な途切れになりにくい。
    description = _truncate_to_chars(
        article.get("description") or "", PAGE3_DESC_MAX_CHARS,
    )
    source_name = article.get("source_name") or ""
    url = article.get("url") or ""
    date_label = _format_publish_date_ja(article.get("pub_date"))
    if date_label:
        byline_text = f"出典：{source_name} · {date_label}"
    else:
        byline_text = f"出典：{source_name}"
    # Sprint 6: タイトルにリンク。URL があれば <a> で囲む（Page IV academic と同形）。
    title_html = (
        f'<a href="{_esc(url)}" target="_blank" rel="noopener noreferrer">{_esc(title)}</a>'
        if url else _esc(title)
    )
    return f"""
      <div class="item"{lang_attr}>
        <div class="kicker">{_esc(kicker)}</div>
        <h5 class="headline-s">{title_html}</h5>
        <p>{_esc(description)}</p>
        <p class="byline" style="font-size: 11px; color: #666; margin-top: 4px;">{_esc(byline_text)}</p>
      </div>""".rstrip()


def _render_page3_placeholder(region: str) -> str:
    """Render a 「本日該当なし」 placeholder item for an unfilled region.

    Per page3_design_v1.md §7.2、最小限の表示（kicker + headline のみ、
    説明文・byline・本文なし）。CSS Grid 罫線ロジックは内容ではなく item の
    インデックス位置で適用されるので、placeholder でも正常配置される。
    """
    display_name = PAGE3_REGION_DISPLAY_NAMES.get(region, region)
    return f"""
      <div class="item" lang="ja">
        <div class="kicker">{_esc(display_name)}</div>
        <h5 class="headline-s" style="font-style: italic; color: #666;">本日該当なし</h5>
      </div>""".rstrip()


def build_page_three_v2(selections: dict) -> str:
    """Assemble the full Page III <section> block.

    ``selections`` is the ``Page3Result.selections`` dict mapping slot keys
    to RegionSelection objects. Order is fixed per PAGE3_DISPLAY_SLOTS
    (1行目 R1/R3/R4、2行目 R5/R6/SER).

    C155 (Sprint 13, 2026-08-10): R2 廃止で 5 領域になり、6 枠目に
    セレンディピティ (SER) が入る。描画は 6 枠とも同一形式。
    """
    items_html: list[str] = []
    for region in PAGE3_DISPLAY_SLOTS:
        sel = selections.get(region)
        if sel is None or sel.article is None:
            items_html.append(_render_page3_placeholder(region))
        else:
            items_html.append(_render_page3_item(sel.article, region))

    items_concat = "\n".join(items_html)
    return f"""<section class="page page-three">
    <div class="page-banner"><span class="pg-num">— Page III —</span> General News · The Wider World, in Brief</div>

    <div class="general-grid">
{items_concat}

    </div>
  </section>"""


def replace_page_three(html_text: str, new_page_html: str) -> str:
    """Surgical replace for Page III, parallel to ``replace_page_two``."""
    start_marker = '<section class="page page-three">'
    if html_text.count(start_marker) != 1:
        raise RuntimeError(
            f"Expected 1 page-three section, found {html_text.count(start_marker)}"
        )
    start = html_text.find(start_marker)
    end = html_text.find("</section>", start)
    if end == -1:
        raise RuntimeError("Page Three section end not found")
    end += len("</section>")
    return html_text[:start] + new_page_html + html_text[end:]


# ---------------------------------------------------------------------------
# Rendering — Page IV ("Arts & Letters")
# ---------------------------------------------------------------------------

# CSS injected into the template's <style> block when Page IV is regenerated.
# Idempotent — guarded by the marker comment so re-injection on overwrite
# doesn't pile up duplicates.


def inject_page_four_css(html_text: str) -> str:
    """Idempotently inject Page IV CSS just before the closing </style> tag.

    Skipped if the marker comment already present (safe re-runs).
    """
    if PAGE_FOUR_CSS_MARKER in html_text:
        return html_text
    end_style_idx = html_text.rfind("</style>")
    if end_style_idx < 0:
        # No <style> block to extend; defensively wrap our own.
        head_close = html_text.find("</head>")
        if head_close < 0:
            return html_text  # malformed template, give up silently
        injected = f"<style>\n{PAGE_FOUR_CSS}\n</style>\n"
        return html_text[:head_close] + injected + html_text[head_close:]
    return html_text[:end_style_idx] + PAGE_FOUR_CSS + html_text[end_style_idx:]


# C55 (Sprint 8, 2026-06-02): page4 concept essay の **bold** マークダウン
# safety net 用 regex。page1_v3.renderer._MARKDOWN_BOLD_RE と同パターン。
# プロンプト側で 1 次対策（concept_writer SYSTEM_PROMPT）、ここで 2 段目のガード。
_PAGE4_CONCEPT_BOLD_RE = re.compile(r"\*\*([^*\n]+?)\*\*")


def _render_page4_related_section(related: list[dict]) -> str:
    """関連概念セクション（C158, Sprint 13, 2026-08-12）。

    C155 で学術ニュース枠を廃止して第4面が概念 1 本だけになったため、
    concepts.yaml のグラフ構造（``related``）を紙面に出して分量を戻しつつ、
    神山さんが「次に掘りたい概念」を見つける導線にする。

    ``related`` が空なら空文字列を返し、セクションごと出さない
    （概念のみのレイアウトに自然に戻る）。
    """
    if not related:
        return ""
    items = []
    for r in related:
        name_ja = _esc(r.get("name_ja", ""))
        name_en = _esc(r.get("name_en", ""))
        note = _esc(r.get("note", ""))
        note = _PAGE4_CONCEPT_BOLD_RE.sub(r"<strong>\1</strong>", note)
        en_html = f'<span class="rc-en">{name_en}</span>' if name_en else ""
        items.append(
            f'        <li class="related-concept-item">\n'
            f'          <span class="rc-name">{name_ja}</span>{en_html}\n'
            f'          <p class="rc-note">{note}</p>\n'
            f'        </li>'
        )
    items_html = "\n".join(items)
    return f"""
      <aside class="related-concepts">
        <div class="rc-heading">この概念とつながるもの</div>
        <ul class="related-concept-list">
{items_html}
        </ul>
      </aside>"""


def _render_page4_concept_column(
    concept: dict, essay: str, related: list[dict] | None = None,
) -> str:
    """Render the left column (concept of the week).

    C55 (Sprint 8, 2026-06-02) — C52 (1 面論考) と同じ二段ガードの 2 段目。
    LLM が出した ``**bold**`` を ``<strong>bold</strong>`` に変換し、紙面に
    記号が漏れる事故を防ぐ。C52 の renderer 安全網と同パターン。
    """
    name_ja = _esc(concept.get("name_ja", ""))
    name_en = _esc(concept.get("name_en", ""))
    domain = _esc(concept.get("domain", ""))
    thinkers = _esc(", ".join(concept.get("thinkers", [])))
    essay_html = _esc(essay)
    # C55 safety net: **bold** → <strong>bold</strong>
    essay_html = _PAGE4_CONCEPT_BOLD_RE.sub(r"<strong>\1</strong>", essay_html)
    return f"""
    <article class="concept-column" lang="ja">
      <div class="kicker">今日の概念</div>
      <h3 class="concept-title">
        {name_ja}
        <span class="concept-en">{name_en}</span>
      </h3>
      <div class="concept-meta">
        <span class="domain">{domain}</span>
        <span class="thinkers">代表：{thinkers}</span>
      </div>
      <div class="concept-essay">
        <p>{essay_html}</p>
      </div>{_render_page4_related_section(related or [])}
    </article>""".rstrip()


# C155 (Sprint 13, 2026-08-10): 学術ニュース 3 本の枠を廃止。
# _render_page4_academic_item / _render_page4_academic_column および
# scripts/page4/article_rotator.py（3 日ローテーション）を削除した。
# 第4面は「今日の概念」1 本のみの面になる。
#
# C155a 実測: stage2.*.page4 は $0.153/日 ($4.66/月) で、再構想で消える
# コストとしては最大。学術ニュースは 3 面 R6「学術・科学」と扱う領域が
# 重なっており、Page IV は概念コラムに純化させる判断（依頼書「新4面」）。


def build_page_four_v2(target_date: date) -> tuple[str, dict]:
    """Build the full <section class="page page-four"> block.

    C155 (Sprint 13, 2026-08-10): 学術ニュース 3 本を廃止し、「今日の概念」
    のみの面にした。概念選出ロジック（222 概念 / 60 日除外窓）は不変。

    C158 (Sprint 13, 2026-08-12): 関連概念セクションを追加。学術ニュース廃止で
    面が概念 1 本だけになり分量的に寂しくなったため、concepts.yaml のグラフ
    構造を紙面に可視化する。関連概念の解説は本文と **同じ 1 回の LLM 呼び出し**
    で生成するのでコスト増はトークン分のみ。

    Returns ``(html, telemetry)`` where telemetry contains:
      - concept: the chosen concept dict
      - essay_result: {essay, related, is_fallback, cost_usd}
    """
    concepts = page4_concept_selector.load_concepts()
    concept = page4_concept_selector.select_concept_for_today(
        today=target_date, concepts=concepts,
    )
    related = page4_related.select_related(concept, concepts)
    essay_result = page4_concept_writer.write_essay(concept, related)

    concept_html = _render_page4_concept_column(
        concept, essay_result["essay"], essay_result.get("related"),
    )

    page = f"""<section class="page page-four">
    <div class="page-banner"><span class="pg-num">— Page IV —</span> Arts &amp; Letters · A Page for Slow Reading</div>

    <div class="page-four-grid page-four-single">
{concept_html}
    </div>
  </section>"""

    telemetry = {
        "concept": concept,
        "essay_result": essay_result,
    }
    return page, telemetry


def replace_page_four(html_text: str, new_page_html: str) -> str:
    """Surgical replace for Page IV, parallel to ``replace_page_three``."""
    start_marker = '<section class="page page-four">'
    if html_text.count(start_marker) != 1:
        raise RuntimeError(
            f"Expected 1 page-four section, found {html_text.count(start_marker)}"
        )
    start = html_text.find(start_marker)
    end = html_text.find("</section>", start)
    if end == -1:
        raise RuntimeError("Page Four section end not found")
    end += len("</section>")
    return html_text[:start] + new_page_html + html_text[end:]


# ---------------------------------------------------------------------------
# Rendering — Page V ("Columns & Serendipity")
# Sprint 4 layout swap: was Page VI in Sprint 3 Step D
# ---------------------------------------------------------------------------



def inject_page_five_css(html_text: str) -> str:
    """Idempotently inject Page V CSS just before </style>."""
    if PAGE_FIVE_CSS_MARKER in html_text:
        return html_text
    end_style_idx = html_text.rfind("</style>")
    if end_style_idx < 0:
        head_close = html_text.find("</head>")
        if head_close < 0:
            return html_text
        injected = f"<style>\n{PAGE_FIVE_CSS}\n</style>\n"
        return html_text[:head_close] + injected + html_text[head_close:]
    return html_text[:end_style_idx] + PAGE_FIVE_CSS + html_text[end_style_idx:]


def _truncate_to_chars(text: str, n: int = 120) -> str:
    if not text:
        return ""
    s = text.strip()
    if len(s) <= n:
        return s
    # Try to break at a sentence boundary
    cut = s[:n]
    for sep in ("。", "．", ".", "\n"):
        idx = cut.rfind(sep)
        if idx >= n // 2:
            return cut[: idx + 1]
    return cut + "…"


def build_page_five_v2(
    target_date: date,
    *,
    page3_result=None,
) -> tuple[str, dict]:
    """Build the full <section class="page page-five"> block.

    C155 (Sprint 13, 2026-08-10): 第5面を「AIかみやまの一筆」100% にした。

    旧構成は上 40% にセレンディピティ記事（今朝出会った1本）、下 60% に一筆
    という 2 枠構成で、両者は別々の記事を扱っていた（Sprint 7 Phase 1 Step 2 で
    独立化）。C155 でセレンディピティ枠は第3面 6 枠目に移設し、第5面は一筆と
    その参照記事サマリだけの面になる。

    参照記事サマリは ``page5/article_summarizer.py`` が Anthropic API で生成する
    （300-400 字目安、第6面コラム同等の品質）。一筆本文は従来通り miibo が
    生成し、両者を並べて表示する。声を混ぜないため、サマリは事実要約に徹する。

    Returns (html, telemetry) — telemetry contains:
      - ai_article (一筆の論評対象記事)
      - summary    (参照記事サマリ {summary, is_fallback, cost_usd})
      - column     (column_title + column_body + is_fallback + elapsed_ms)
    """
    from .page5 import ai_kamiyama_selector as page5_ai_selector
    from .page5 import article_summarizer as page5_summarizer

    # 1) 一筆の対象記事を選ぶ。
    #    候補プール = Page III 確定 6 枠 + Page III 不採用の評価済み上位候補。
    #    後者は Page III が既に採点済なので追加 LLM コストは 0。
    page3_selections = (
        getattr(page3_result, "selections", None) if page3_result is not None else None
    )
    page3_runner_ups = (
        getattr(page3_result, "runner_up_candidates", None)
        if page3_result is not None else None
    )
    # C168: 過去 PAGE5_DEDUP_DAYS 日に 5 面で採用した URL を除外する。
    recent_page5_urls = load_recently_displayed_urls(
        PAGE5_DEDUP_DAYS, page="page5", until_date=target_date,
    )
    # C190: 全期間で一度でも 5 面に出た URL。未出優先（段 2）の判定に使う。
    ever_page5_urls = load_recently_displayed_urls(
        PAGE5_UNSEEN_LOOKBACK_DAYS, page="page5", until_date=target_date,
    )
    ai_article = page5_ai_selector.select_ai_kamiyama_article(
        target_date=target_date,
        page3_selections=page3_selections,
        page3_runner_ups=page3_runner_ups,
        exclude_urls=recent_page5_urls,
        ever_used_urls=ever_page5_urls,
        registry=None,
        eligible_categories=None,
    )

    # 2) 候補ゼロなら面ごと休載（miibo も要約 API も呼ばない）
    if ai_article is None:
        return _render_page_five_placeholder(), {
            "ai_article": None,
            "summary": None,
            "column": None,
        }

    # 3) 参照記事の日本語サマリ（Tribune 側 = Anthropic API）
    summary = page5_summarizer.summarize_article(ai_article)

    # 4) 一筆本文（miibo）
    column = page5_ai_kamiyama.write_column(ai_article)

    html = _render_page_five(ai_article, summary, column)
    return html, {
        "ai_article": ai_article,
        "summary": summary,
        "column": column,
    }


def _render_page_five(
    ai_article: dict,
    summary: dict,
    column: dict,
) -> str:
    """Render Page V: 参照記事サマリ + AIかみやまの一筆（面全体）。

    C155: 旧 2 枠構成（上=セレンディピティ / 下=一筆）から、一筆 100% + その
    参照記事サマリ併載に変更。読者が「何への論評か」を紙面内で完結して
    理解できるようにする。
    """
    title = (ai_article.get("title_ja") or ai_article.get("title") or "").strip()
    source_name = (ai_article.get("source_name") or "").strip()
    url = (ai_article.get("url") or "").strip()
    date_label = _format_publish_date_ja(ai_article.get("pub_date"))
    byline = f"出典：{source_name} · {date_label}" if date_label else f"出典：{source_name}"

    title_html = (
        f'<a href="{_esc(url)}" target="_blank" rel="noopener noreferrer">{_esc(title)}</a>'
        if url else _esc(title)
    )

    column_title = column.get("column_title", "")
    column_body = column.get("column_body", "")

    return f"""<section class="page page-five">
    <div class="page-banner"><span class="pg-num">— Page V —</span> AI Kamiyama's Column · One Article, Read Closely</div>

    <div class="page-five-content" lang="ja">
      <aside class="reference-article">
        <div class="kicker">一筆が読んだ記事</div>
        <h3 class="article-title">{title_html}</h3>
        <p class="reference-summary">{_esc(summary.get("summary", ""))}</p>
        <p class="reference-byline">{_esc(byline)}</p>
      </aside>

      <article class="ai-kamiyama-column">
        <div class="kicker">AIかみやまの一筆</div>
        <h3 class="column-title">{_esc(column_title)}</h3>
        <div class="column-body">
          <p>{_esc(column_body)}</p>
        </div>
        <p class="ai-byline">— AIかみやま</p>
      </article>
    </div>
  </section>"""


def _render_page_five_placeholder() -> str:
    """Render the 休載 placeholder (一筆の対象記事が候補ゼロ)."""
    return """<section class="page page-five">
    <div class="page-banner"><span class="pg-num">— Page V —</span> AI Kamiyama's Column · One Article, Read Closely</div>

    <div class="page-five-placeholder" lang="ja">
      <p>本日 AIかみやま は休載です。</p>
      <p>一筆に渡す記事の候補がありませんでした。</p>
    </div>
  </section>"""


def replace_page_five(html_text: str, new_page_html: str) -> str:
    """Surgical replace for Page V."""
    start_marker = '<section class="page page-five">'
    if html_text.count(start_marker) != 1:
        raise RuntimeError(
            f"Expected 1 page-five section, found {html_text.count(start_marker)}"
        )
    start = html_text.find(start_marker)
    end = html_text.find("</section>", start)
    if end == -1:
        raise RuntimeError("Page Five section end not found")
    end += len("</section>")
    return html_text[:start] + new_page_html + html_text[end:]


# ---------------------------------------------------------------------------
# Rendering — Page VI ("Leisure")
# Sprint 4 layout swap: was Page V in Sprint 3 Step C
# ---------------------------------------------------------------------------



def inject_page_six_css(html_text: str) -> str:
    """Idempotently inject Page VI CSS just before </style>."""
    if PAGE_SIX_CSS_MARKER in html_text:
        return html_text
    end_style_idx = html_text.rfind("</style>")
    if end_style_idx < 0:
        head_close = html_text.find("</head>")
        if head_close < 0:
            return html_text
        injected = f"<style>\n{PAGE_SIX_CSS}\n</style>\n"
        return html_text[:head_close] + injected + html_text[head_close:]
    return html_text[:end_style_idx] + PAGE_SIX_CSS + html_text[end_style_idx:]


def _render_leisure_column(
    *,
    area_label: str,
    column_class: str,
    result: dict,
) -> str:
    """One column for books / music / outdoor.

    ``result`` is the dict returned by ``leisure_recommender.recommend_for_area``.

    Sprint 6: column-title は Tribune オリジナルのコラム題目（元記事タイトルでは
    ない）のためリンクしない。元記事への動線は byline の出典名にリンクを置く。

    Sprint 5 task #4 (2026-05-04): focus_work（題材表記）を column-title 直下に
    表示。LLM が空文字列を返した場合 / fallback 時は <p> 自体を省略して
    紙面構造を保つ（cooking の dish_name と対称構造）。
    """
    column_title = result.get("column_title", "")
    column_body = result.get("column_body", "")
    focus_work = (result.get("focus_work") or "").strip()
    article = result.get("article")
    focus_work_html = (
        f'\n      <p class="focus-work">{_esc(focus_work)}</p>'
        if focus_work else ""
    )

    if article is not None:
        source_name = article.get("source_name", "")
        url = article.get("url", "")
        date_label = _format_publish_date_ja(article.get("pub_date"))
        # Sprint 6: 出典名に <a>。{byline_html} は f-string 内で _esc() を通さず
        # そのまま挿入する（<a> タグを保持するため、source_name は事前 escape 済）。
        source_html = (
            f'<a href="{_esc(url)}" target="_blank" rel="noopener noreferrer">{_esc(source_name)}</a>'
            if url else _esc(source_name)
        )
        if date_label:
            byline_html = f"出典：{source_html} · {_esc(date_label)}"
        else:
            byline_html = f"出典：{source_html}"
    else:
        byline_html = "本紙編集部"

    return f"""
    <article class="leisure-column-v2 {column_class}" lang="ja">
      <div class="kicker">{_esc(area_label)}</div>
      <h3 class="column-title">{_esc(column_title)}</h3>{focus_work_html}
      <div class="column-body">
        <p>{_esc(column_body)}</p>
      </div>
      <p class="byline-v2">{byline_html}</p>
    </article>""".rstrip()


def _render_cooking_column(result: dict) -> str:
    """The 4th column — cooking is structurally different (dish_name + ingredients)."""
    return f"""
    <article class="leisure-column-v2 cooking-column-v2" lang="ja">
      <div class="kicker">料理</div>
      <h3 class="column-title">{_esc(result.get("column_title", ""))}</h3>
      <p class="dish-name">{_esc(result.get("dish_name", ""))}</p>
      <p class="ingredients">{_esc(result.get("ingredients_summary", ""))}</p>
      <div class="column-body">
        <p>{_esc(result.get("column_body", ""))}</p>
      </div>
      <p class="byline-v2">Tribune厨房</p>
    </article>""".rstrip()


def build_page_six_v2(
    target_date: date,
    *,
    pre_evaluated: dict[str, dict] | None = None,
    displayed_urls_today: set[str] | None = None,
) -> tuple[str, dict]:
    """Build the full <section class="page page-six"> block (Leisure 4 columns).

    Parameters
    ----------
    displayed_urls_today :
        C139 (Sprint 12, 2026-07-10): 当日既に他面で採用済の URL 集合。
        Page IV の同名引数と対称的な設計。全 area (books/music/outdoor)
        の ``recommend_for_area`` に流して同日 cross-page dedup を行う。
        Page V serendipity 記事の URL がここに入る想定
        （呼出側で orchestrate、Page V build → Page VI build の順序前提）。

    Returns (html, telemetry).
    """
    # 1) Books / Music / Outdoor — recommend + LLM column
    books = page6_leisure.recommend_for_area(
        "books", target_date=target_date, pre_evaluated=pre_evaluated,
        displayed_urls_today=displayed_urls_today,
    )
    music = page6_leisure.recommend_for_area(
        "music", target_date=target_date, pre_evaluated=pre_evaluated,
        displayed_urls_today=displayed_urls_today,
    )
    outdoor = page6_leisure.recommend_for_area(
        "outdoor", target_date=target_date, pre_evaluated=pre_evaluated,
        displayed_urls_today=displayed_urls_today,
    )

    # 2) Cooking — LLM autonomous
    cooking = page6_cooking.generate_cooking_column(target_date=target_date)

    # 3) Render
    books_html = _render_leisure_column(
        area_label="読書", column_class="books-column-v2", result=books,
    )
    music_html = _render_leisure_column(
        area_label="音楽", column_class="music-column-v2", result=music,
    )
    outdoor_html = _render_leisure_column(
        area_label="アウトドア", column_class="outdoor-column-v2", result=outdoor,
    )
    cooking_html = _render_cooking_column(cooking)

    page = f"""<section class="page page-six">
    <div class="page-banner"><span class="pg-num">— Page VI —</span> Leisure · Reading, Music, Trail &amp; Table</div>

    <div class="page-six-grid-v2">
{books_html}
{music_html}
{outdoor_html}
{cooking_html}
    </div>
  </section>"""

    telemetry = {
        "books": books,
        "music": music,
        "outdoor": outdoor,
        "cooking": cooking,
    }
    return page, telemetry


# ---------------------------------------------------------------------------
# Editorial postscript (Sprint 4 Phase 3, 2026-05-03)
# ---------------------------------------------------------------------------

def _render_editorial_footer(
    editorial_result: dict, target_date: date | None = None,
) -> str:
    """Build the <footer class="editorial-footer"> HTML block.

    Returns "" when the editorial generation fell back, so the caller can skip
    inserting the footer entirely (paper ends at Page VI on fallback days).

    C69 (Sprint 9, 2026-06-09) — 旧 C37/C64 で footer 直下に置いていた
    「コメントを書く →」CTA を 1 面右下に移設（_render_page_one_comment_cta /
    page1_v3 renderer 側でレンダリング）。``target_date`` 引数は呼出側
    互換のため残置するが本関数では未使用。
    """
    if not editorial_result or editorial_result.get("is_fallback"):
        return ""
    body = editorial_result.get("body") or ""
    if not body.strip():
        return ""
    return f"""<footer class="editorial-footer">
    <div class="editorial-footer-inner">
      <div class="label">編集後記</div>
      <div class="body">
        <p>{_esc(body)}</p>
      </div>
      <div class="signature">— Tribune 編集部</div>
    </div>
  </footer>

  """


def render_page_one_comment_cta(target_date: date) -> str:
    """1 面右下の「コメントを書く →」CTA HTML を返す（C69, 2026-06-09）.

    神山さん要望：「1 面を見て感想を書くので、コメント CTA は 1 面右下に
    あってほしい」「右下が空く問題も解決」。C37 / C64 で editorial-footer
    直下に置いていた CTA を本ヘルパー経由で 1 面 (page-one / page-one-v3)
    の section 末尾に挿入し、CSS で position:absolute で右下に貼り付ける。
    """
    date_iso = _esc(target_date.isoformat())
    return (
        f'<div class="page-one-cta">'
        f'<a href="/comment?date={date_iso}" '
        f'target="_blank" rel="noopener">コメントを書く →</a>'
        f'</div>'
    )


def insert_editorial_footer(html_text: str, footer_html: str) -> str:
    """Insert the editorial footer just before <footer class="colophon">.

    Idempotent on empty footer_html (returns html_text unchanged). If the
    colophon marker is missing (template malformed), inserts before </body>
    as a defensive fallback so the editorial isn't silently dropped.
    """
    if not footer_html:
        return html_text
    # Avoid double insertion: if our editorial-footer already exists, skip.
    if '<footer class="editorial-footer">' in html_text:
        return html_text
    marker = '<footer class="colophon">'
    pos = html_text.find(marker)
    if pos >= 0:
        return html_text[:pos] + footer_html + html_text[pos:]
    body_close = html_text.rfind("</body>")
    if body_close < 0:
        return html_text  # malformed template, give up silently
    return html_text[:body_close] + footer_html + html_text[body_close:]


def replace_page_six(html_text: str, new_page_html: str) -> str:
    """Surgical replace for Page VI."""
    start_marker = '<section class="page page-six">'
    if html_text.count(start_marker) != 1:
        raise RuntimeError(
            f"Expected 1 page-six section, found {html_text.count(start_marker)}"
        )
    start = html_text.find(start_marker)
    end = html_text.find("</section>", start)
    if end == -1:
        raise RuntimeError("Page Six section end not found")
    end += len("</section>")
    return html_text[:start] + new_page_html + html_text[end:]


# ---------------------------------------------------------------------------
# Template date manipulation
# ---------------------------------------------------------------------------

def issue_number(target: date, archive_dir: Path | None = None) -> tuple[int, int]:
    """Vol/No を archive ディレクトリ数ベースで計算する。

    Vol: 年単位（2026 = Vol 1、2027 = Vol 2 ...）
    No:  archive/YYYY-*.html のうち target.isoformat() 以下のファイル数
         - 当日 archive が既存（再生成時）→ そのまま通番
         - 当日 archive が無い（新規生成時）→ 既存数 + 1

    archive_dir はテスト時に差し替え可能（デフォルトは ARCHIVE_DIR）。
    """
    if archive_dir is None:
        archive_dir = ARCHIVE_DIR

    vol = target.year - 2026 + 1

    target_iso = target.isoformat()
    target_year = str(target.year)

    # YYYY-MM-DD.html パターンのみ対象（_logo_preview などは除外）
    archives = sorted(
        f.stem for f in archive_dir.glob(f"{target_year}-*.html")
        if not f.stem.startswith("_")
    )

    earlier_or_same = [a for a in archives if a <= target_iso]

    if target_iso in earlier_or_same:
        no = len(earlier_or_same)
    else:
        no = len(earlier_or_same) + 1

    return (vol, no)


def _format_date_strings(target: date) -> dict[str, str]:
    """Return the strings used for masthead/title/footer substitution."""
    dow_en = _DOW_EN[target.weekday()]
    dow_ja = _DOW_JA[target.weekday()]
    return {
        "title_long": f"{dow_en}, {target.strftime('%B %-d, %Y')}",   # Wednesday, April 29, 2026
        "masthead":   f"{dow_en}, {target.strftime('%B %-d, %Y')} ／ {target.year}年{target.month}月{target.day}日　{dow_ja}曜日",
        "footer_built_in": f"{target.strftime('%B %-d, %Y')}",         # April 29, 2026
    }


def update_template_date_strings(template_html: str, target: date) -> str:
    """Replace the 4/25 date strings in the template with target-date equivalents.

    Vol/No は ``issue_number(target)`` で動的採番し、masthead と colophon の
    両方を一括置換する。
    """
    new = _format_date_strings(target)
    out = template_html

    # Title: <title>Kamiyama Tribune — Saturday, April 25, 2026</title>
    out = out.replace(
        "Kamiyama Tribune — Saturday, April 25, 2026",
        f"Kamiyama Tribune — {new['title_long']}",
    )
    # Masthead: <span class="center">Saturday, April 25, 2026 ／ 2026年4月25日　土曜日</span>
    out = out.replace(
        "Saturday, April 25, 2026 ／ 2026年4月25日　土曜日",
        new["masthead"],
    )
    # Footer "Built in residence on April 25, 2026"
    out = out.replace(
        "Built in residence on April 25, 2026",
        f"Built in residence on {new['footer_built_in']}",
    )
    # Vol/No: 動的採番（archive 数ベース）。masthead と colophon の両方を置換。
    vol, no = issue_number(target)
    out = out.replace("Vol. 1, No. 1", f"Vol. {vol}, No. {no}")
    return out


# ---------------------------------------------------------------------------
# Output / index helpers
# ---------------------------------------------------------------------------

def _archive_path(target: date) -> Path:
    return ARCHIVE_DIR / f"{target.isoformat()}.html"


def update_index_redirect(target: date) -> None:
    """Rewrite ``index.html`` so the meta-refresh + canonical point to the
    target archive. Called only when ``--update-index`` is passed."""
    if not INDEX_HTML.exists():
        print(f"  [warn] {INDEX_HTML} not found, skipping --update-index", file=sys.stderr)
        return
    text = INDEX_HTML.read_text(encoding="utf-8")
    new_target = f"archive/{target.isoformat()}.html"
    updated = re.sub(
        r"archive/\d{4}-\d{2}-\d{2}\.html",
        new_target,
        text,
    )
    INDEX_HTML.write_text(updated, encoding="utf-8")
    print(f"  Updated {INDEX_HTML} → redirect to {new_target}", file=sys.stderr)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _make_dedup_aware_page2_fetcher(target: date, days_back: int = PAGE2_DEDUP_DAYS):
    """Wrap ``page2_default_fetcher`` so each ``companies:*`` fetch removes
    articles whose URL was displayed on Page II of that company in the
    past ``days_back`` days.

    Two category forms are handled:

    * Specific (``"companies:Cocolomi"`` etc.) — dedup against that single
      company's displayed_urls. Used by Page II's per-company fallback
      fetches (Medium / Reference) inside ``page2.run_page2_pipeline``.
    * Broad (``"companies:"``) — articles span all 3 companies. Each
      article is attributed via its ``category`` field and deduped against
      that specific company's displayed_urls. Used by the **initial**
      High-pool fetch in ``_run_page2_selection``.

    Cross-industry fetches (``category="business"`` / ``"geopolitics"``)
    are **not** deduplicated — they intentionally cast a wide net and the
    same article may serve as fallback for multiple companies.
    """
    # Pre-compute the displayed URL set per company once per fetcher
    # instance — these are immutable for the duration of the run.
    displayed_per_company: dict[str, set[str]] = {
        ck: load_recently_displayed_urls(
            days_back=days_back, page="page2", company_key=ck, until_date=target,
        )
        for ck in PAGE2_CATEGORY_TO_KEY.values()
    }

    def wrapped(*, name_substring=None, category=None, priority=None, limit=8, **kw):
        articles = page2_default_fetcher(
            name_substring=name_substring,
            category=category,
            priority=priority,
            limit=limit,
            **kw,
        )
        if not (category and category.startswith("companies:")):
            return articles  # cross-industry: no dedup

        # Specific category: single-company dedup.
        if category in PAGE2_CATEGORY_TO_KEY:
            company_key = PAGE2_CATEGORY_TO_KEY[category]
            displayed = displayed_per_company.get(company_key, set())
            if displayed:
                before = len(articles)
                articles = filter_recently_displayed(articles, displayed)
                removed = before - len(articles)
                if removed:
                    print(
                        f"  [dedup] {category} priority={priority}: "
                        f"removed {removed}/{before} recently-displayed",
                        file=sys.stderr,
                    )
            return articles

        # Broad "companies:" — attribute each article to its specific
        # company via Source.category, then dedup against THAT company's
        # window. Articles whose category cannot be resolved are kept
        # (defensive: we don't drop articles we can't identify).
        filtered: list[dict] = []
        per_company_removed: dict[str, int] = {}
        for art in articles:
            art_cat = art.get("category")
            ck = PAGE2_CATEGORY_TO_KEY.get(art_cat) if art_cat else None
            if not ck:
                filtered.append(art)
                continue
            displayed = displayed_per_company.get(ck, set())
            if art.get("url") in displayed:
                per_company_removed[ck] = per_company_removed.get(ck, 0) + 1
                continue
            filtered.append(art)
        for ck, n in per_company_removed.items():
            print(
                f"  [dedup] {category} (broad) priority={priority}: "
                f"removed {n} for company={ck}",
                file=sys.stderr,
            )
        return filtered

    return wrapped


def _run_page2_selection(target: date, *, write_log: bool, threshold: float):
    """Fetch companies:* High → run page2 pipeline → return Page2Result.

    Separated from main() for clarity; called whether dry-run or production
    so dry-run output can show the Page II selections too.

    Sprint 2 Step D: dedup-aware fetcher を使用し、initial High pool +
    Medium/Reference fallback すべてに 3-day 社別 dedup を適用する。
    cross-industry stage は意図的に dedup なし。
    """
    print(
        "Fetching companies.md High Priority for Page II selection (with 3-day dedup)…",
        file=sys.stderr,
    )
    dedup_fetcher = _make_dedup_aware_page2_fetcher(target)
    # Initial High pool — dedup applied via the wrapped fetcher.
    companies_scored = dedup_fetcher(
        category="companies:", priority="high", limit=8, no_dedupe=True,
    )
    print(
        f"  got {len(companies_scored)} scored articles for Page II "
        "(post-dedup)",
        file=sys.stderr,
    )

    # Per-company exhaustion check on initial pool.
    page2_exhaustion: dict[str, int] = {}
    for art in companies_scored:
        cat = art.get("category")
        ck = PAGE2_CATEGORY_TO_KEY.get(cat) if cat else None
        if ck:
            page2_exhaustion[ck] = page2_exhaustion.get(ck, 0) + 1
    for ck in PAGE2_COMPANY_ORDER:
        if page2_exhaustion.get(ck, 0) == 0:
            display = COMPANY_DISPLAY_META[ck][0]
            print(
                f"  WARNING: {display} 候補枯渇 (initial High pool が"
                f"dedup 後に 0 件、fallback stage に依存)",
                file=sys.stderr,
            )

    # Sprint 8 C29 (2026-05-25): Stage 4 共有 broad pool を 1 回だけ事前 fetch。
    # 5/24 GHA cron で観察された Page II 34 分肥大（3 社が独立に
    # business/geopolitics × high/medium の 4 fetch を呼んでいた重複 12 fetch）
    # を構造的に解消。各社 Stage 4 は keyword pre-filter + Step 1 評価のみ。
    print(
        "Preparing shared cross-industry pool for Page II Stage 4 (C29)…",
        file=sys.stderr,
    )
    shared_cross_pool = prepare_shared_cross_industry_pool(dedup_fetcher)
    print(
        f"  shared cross-industry pool: {len(shared_cross_pool)} 件 "
        "(fetch 12 → 4 回に削減、3 社の Stage 2 重複解消)",
        file=sys.stderr,
    )

    print(
        "Running Page II pipeline (Step 1 + selection + Step 2)…",
        file=sys.stderr,
    )
    page2_result = run_page2_pipeline(
        companies_scored,
        fetcher_fn=dedup_fetcher,  # ← wrapped fetcher applies dedup to fallbacks too
        write_log=write_log,
        today=target,
        threshold=threshold,
        cross_industry_articles=shared_cross_pool,
    )
    page2_result._exhaustion_initial = page2_exhaustion  # type: ignore[attr-defined]
    return page2_result


def _run_page3_selection(
    target: date,
    *,
    page2_result,
    write_log: bool,
):
    """Page III pipeline: 5領域 + セレンディピティ 1枠.

    C155 (Sprint 13, 2026-08-10): page1_master 廃止に伴い ``pre_evaluated``
    による Stage 2 結果共有は消滅した（page3_design_v1.md §10.4 は無効）。
    page3 は自前で全候補を評価する。C155a の実測では page1 の 63 URL は
    page3 の 303 URL の完全な部分集合だったため、評価対象の総数は不変で、
    コストが page1_master タグから page3 タグへ付け替わるだけである。
    """
    print(
        "Fetching business + geopolitics + academic + books for Page III...",
        file=sys.stderr,
    )

    # 当日 page2 で選定された URL を当日他面 dedup として渡す。
    today_urls: set[str] = set()
    if page2_result is not None:
        for sel in page2_result.selections.values():
            if sel.article is not None:
                url = sel.article.get("url")
                if url:
                    today_urls.add(url)

    # 過去 N=7 日の page3 dedup。
    past_urls = load_recently_displayed_urls(
        days_back=7, page="page3", until_date=target,
    )
    if past_urls:
        print(
            f"  [dedup] Page III: past 7 days has {len(past_urls)} URLs to exclude",
            file=sys.stderr,
        )

    print(
        "Running Page III pipeline (Stage 1 → 2 → 3 + 領域振分け)...",
        file=sys.stderr,
    )
    page3_result = run_page3_pipeline(
        target_date=target,
        pre_evaluated=None,
        displayed_urls_today=today_urls,
        displayed_urls_past_n=past_urls,
        write_log=write_log,
    )
    print(
        f"  Page III: {6 - page3_result.placeholder_count}/6 regions filled, "
        f"cost=${page3_result.cost_usd:.4f}",
        file=sys.stderr,
    )
    return page3_result


def _print_page3_report(page3_result) -> None:
    print()
    print("=== Page III selections ===")
    print(f"  candidates: {page3_result.candidates_total} total → "
          f"{page3_result.candidates_after_dedup} after dedup")
    print(f"  cost (Stage 2 LLM): ${page3_result.cost_usd:.4f}")
    print(f"  placeholders: {page3_result.placeholder_count}/6")
    print()
    for region in PAGE3_DISPLAY_SLOTS:
        sel = page3_result.selections.get(region)
        display = PAGE3_REGION_DISPLAY_NAMES[region]
        if sel is None or sel.article is None:
            print(f"  [{region} {display:<18}] 本日該当なし  ({sel.fallback_reason if sel else 'no entry'})")
            if sel is not None and sel.fallback_detail:
                print(f"      理由: {sel.fallback_detail}")
            continue
        art = sel.article
        kicker = _page3_generate_kicker(art, region)
        print(
            f"  [{region} {display:<18}] score={sel.final_score:6.2f}  "
            f"kicker={kicker:<14}  ({art.get('source_name', '')[:25]})"
        )
        print(f"      title: {art.get('title', '')[:70]}")


def _print_page2_report(page2_result) -> None:
    print()
    print("=== Page II selections ===")
    print(f"  threshold: {page2_result.threshold}")
    print(f"  cost (Step 1 + Step 2 LLM): ${page2_result.cost_usd:.4f}")
    print(f"  errors: {len(page2_result.errors)}")
    print()
    for company_key in PAGE2_COMPANY_ORDER:
        sel = page2_result.selections.get(company_key)
        display, biz = COMPANY_DISPLAY_META[company_key]
        if sel is None or sel.article is None:
            reason = sel.fallback_reason if sel else "no entry"
            print(f"  [{display:<14}] stage={(sel.stage_used if sel else 'none'):<14} → 本日休載  ({reason})")
            continue
        print(
            f"  [{display:<14}] stage={sel.stage_used:<14} score={sel.page2_final_score:6.2f}  "
            f"({sel.article.get('source_name','')[:25]})"
        )
        print(f"      title: {sel.article.get('title', '')[:80]}")
        print(f"      問い:  {sel.morning_question}")
        if sel.fallback_reason:
            print(f"      fallback: {sel.fallback_reason[:120]}")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="regen_front_page_v2",
        description=(
            "Phase 2 美意識 selection pipeline → archive/<date>.html "
            "(Page I + Page II)"
        ),
    )
    p.add_argument(
        "--date",
        help="ISO date (YYYY-MM-DD), defaults to today",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="run pipeline and print candidates; do not write HTML",
    )
    p.add_argument(
        "--update-index",
        action="store_true",
        help="also rewrite index.html to redirect to the new archive file",
    )
    p.add_argument(
        "--page2-threshold", type=float, default=PAGE2_THRESHOLD,
        help=(
            "page2_final_score threshold for Page II selection "
            f"(default {PAGE2_THRESHOLD}, Sprint 2 Step B operational value)"
        ),
    )
    p.add_argument(
        "--skip-page2", action="store_true",
        help="skip Page II generation entirely (Page I only, debug aid)",
    )
    p.add_argument(
        "--skip-page3", action="store_true",
        help="skip Page III generation (Page I + II only, debug aid)",
    )
    p.add_argument(
        "--skip-page4", action="store_true",
        help="skip Page IV generation (Page I + II + III only, debug aid)",
    )
    p.add_argument(
        "--skip-page5", action="store_true",
        help="skip Page V generation (Page I+II+III+IV only, debug aid)",
    )
    p.add_argument(
        "--skip-page6", action="store_true",
        help="skip Page VI generation (Page I+II+III+IV+V only, debug aid)",
    )
    p.add_argument(
        "--skip-editorial", action="store_true",
        help="skip the Tribune editorial postscript (cost-saving / debug aid)",
    )
    args = p.parse_args(argv)

    if args.date:
        try:
            target = date.fromisoformat(args.date)
        except ValueError:
            print(f"invalid --date {args.date!r}", file=sys.stderr)
            return 1
    else:
        target = jst_today()

    print(f"Target date: {target.isoformat()}", file=sys.stderr)

    # 1-2) C155 (Sprint 13, 2026-08-10): v2 Page I パイプライン廃止。
    #
    # Phase 3 (2026-05-23) 以降、本番 cron は regen_front_page_v3 経由で走り、
    # v2 が組んだ「トップ1本 + セカンド3本」の Page I は毎朝 essay 形式に
    # surgical swap されて紙面に出ていなかった。にもかかわらず fetch →
    # Stage 1 → Stage 2 (caller=page1_master) → 翻訳 → build_page_one_v2 が
    # 毎日フル実行されていた。
    #
    # C155a 計測 (2026-08-10, 8/1-8/10 の GHA artifact 10 日分):
    #   * page1_master Stage 2      $0.0615/日 ($1.87/月)
    #   * page1 レンダ側 LLM        $0.0208/日 ($0.63/月)
    #     (page1.lead_deck + page1.why_important)
    #
    # ただし page1_master の Stage 2 は「純粋な無駄」ではなかった。page3 /
    # page4 / page5 / page6 が ``pre_evaluated`` 経由で評価結果を共有しており、
    # 重複 URL の再評価を免れていたためである。C155a で page1 / page3 の fetch
    # を実測したところ **page1 の 63 URL は page3 の 303 URL の完全な部分集合**
    # (63/63 = 100%、page1 専用 URL は 0 本) だった。したがって page1_master を
    # 止めると Stage 2 コストは消えるのではなく page3 に付け替わる。
    # 実質的な削減は render 側の $0.63/月 のみ、という前提で本変更を行う。
    #
    # Page I の HTML は v3 (regen_front_page_v3) が組む。本 module は
    # ``<section class="page page-one">`` の最小プレースホルダのみ出力し、
    # v3 がそこへ swap する二段構成を維持する（月次選定未投入週は
    # プレースホルダがそのまま残るフェイルセーフ）。
    #
    # revert: git tag ``pre-c155-baseline`` を参照。docs/paper_structure_v2.md §8。

    # 3) Page II pipeline (independent fetch from companies.md High)
    page2_result = None
    if not args.skip_page2:
        page2_result = _run_page2_selection(
            target, write_log=not args.dry_run, threshold=args.page2_threshold,
        )

    # 3b) Page III pipeline (Sprint 3 Step A → C155 で 5領域 + セレンディピティ).
    # C155: page1_master 廃止に伴い ``pre_evaluated`` 共有は消滅。page3 が
    # 自前で全候補（旧 page1 の 7 ソースを含む superset）を評価する。
    page3_result = None
    if not args.skip_page3:
        page3_result = _run_page3_selection(
            target,
            page2_result=page2_result,
            write_log=not args.dry_run,
        )

    if args.dry_run:
        if page2_result is not None:
            _print_page2_report(page2_result)
        if page3_result is not None:
            _print_page3_report(page3_result)
        return 0

    # 4) Translate Page II articles.
    if page2_result is not None:
        page2_articles = [
            sel.article for sel in page2_result.selections.values()
            if sel.article is not None
        ]
        if page2_articles:
            print("Translating Page II articles...", file=sys.stderr)
            translate_for_render(page2_articles)

    # 4b) Page IV pipeline: 今日の概念のみ（C155 で学術ニュース 3 本を廃止）。
    page_four_html: str | None = None
    page_four_telemetry: dict | None = None
    page_five_html: str | None = None
    page_five_telemetry: dict | None = None
    page_six_html: str | None = None
    page_six_telemetry: dict | None = None
    if not args.skip_page4:
        print("Building Page IV (今日の概念)...", file=sys.stderr)
        # C155: 学術ニュース枠の廃止により、Page IV は外部記事を一切持たない。
        # C49 案A の cross-page dedup（Page III 採用 URL の除外）は対象が
        # 消えたため不要になった。
        try:
            page_four_html, page_four_telemetry = build_page_four_v2(target)
            essay_meta = page_four_telemetry["essay_result"]
            print(
                f"  Page IV: concept={page_four_telemetry['concept']['id']}, "
                f"essay_fallback={essay_meta['is_fallback']}, "
                f"cost=${essay_meta['cost_usd']:.4f}",
                file=sys.stderr,
            )
        except Exception as e:
            print(
                f"[page4] FAILED: {type(e).__name__}: {e} — skipping Page IV regen",
                file=sys.stderr,
            )
            page_four_html = None

    # 4b.5) C155 (Sprint 13, 2026-08-10): Today's Headlines 廃止。
    #
    # Headlines は Page I の ``candidates_scored`` を候補プールにしていたため、
    # v2 page1 パイプライン廃止と同時に枠ごと消滅する（依頼書「裏側の構造変更 1:
    # Today's Headlines の候補プール依存 → 枠ごと消滅」）。
    #
    # C155a で判明した副次事実：LLM 要約経路は BBC 記事限定だが、
    # ``BbcArticleScraper`` の ``sc-`` prefix 正規表現が BBC の CSS 変更で
    # マッチしなくなっており、8/1-8/10 の 10 日間で
    # ``page2.headlines_summary`` タグの呼び出しは 0 件だった。結果として
    # Headlines には RSS の英語 description が翻訳も要約もされずに出ていた。
    # 廃止によりこの品質問題も同時に解消される。

    # 4c) Page V pipeline: AIかみやまの一筆 100% + 参照記事サマリ（C155）
    if not args.skip_page5:
        print(
            "Building Page V (参照記事サマリ + AIかみやまの一筆 via miibo)...",
            file=sys.stderr,
        )
        try:
            page_five_html, page_five_telemetry = build_page_five_v2(
                target, page3_result=page3_result,
            )
            ai_art = page_five_telemetry.get("ai_article")
            col = page_five_telemetry.get("column")
            summ = page_five_telemetry.get("summary")
            if ai_art is None:
                print("  Page V: PLACEHOLDER (一筆の対象記事が候補ゼロ)", file=sys.stderr)
            else:
                col_status = (
                    "fallback" if col["is_fallback"]
                    else f"AIかみやま OK ({col['elapsed_ms']}ms)"
                )
                summ_status = (
                    "fallback" if summ.get("is_fallback")
                    else f"{len(summ.get('summary') or '')}字"
                )
                print(
                    f"  Page V: ai_kamiyama={ai_art.get('source_name', '')[:20]}, "
                    f"summary={summ_status}, column={col_status}",
                    file=sys.stderr,
                )
        except Exception as e:
            print(
                f"[page5] FAILED: {type(e).__name__}: {e} — skipping Page V regen",
                file=sys.stderr,
            )
            page_five_html = None

    # 4d) Page VI pipeline (Sprint 4: Leisure 4 columns, was Sprint 3 Step C)
    if not args.skip_page6:
        print("Building Page VI (books + music + outdoor + cooking)...", file=sys.stderr)
        # C155: page1_master 廃止で pre_evaluated 共有元が消滅。page6 は自前評価。
        # （page1 の 7 ソースは business/geopolitics 系で page6 の
        #   books/music/outdoor とほぼ重ならず、共有の実効は元々小さかった）
        pre_evaluated_for_page6: dict[str, dict] | None = None
        # C139 (Sprint 12, 2026-07-10) → C155 で再配線。
        #
        # 旧: Page V serendipity 記事の URL を Page VI に渡す（Page V → Page VI 順）。
        # 新: セレンディピティ枠は Page III に移ったため、**Page III の全採用
        #     URL**（5 領域 + セレンディピティ枠）を Page VI に渡す。build 順序は
        #     Page III (§3b) → Page VI (§4d) で Page III が先なので順序は保証済み。
        #     Page III が None / 例外の場合は set() で dedup は no-op。
        #
        # C138 で観測された Stereogum の Page V / Page VI music 二重採用は、
        # 移設後は「Page III セレンディピティ枠 / Page VI music」の衝突として
        # 同じ経路で防がれる。
        page6_other_pages_urls: set[str] = set()
        if page3_result is not None:
            for sel in page3_result.selections.values():
                art = getattr(sel, "article", None)
                if art and art.get("url"):
                    page6_other_pages_urls.add(art["url"])
        try:
            page_six_html, page_six_telemetry = build_page_six_v2(
                target, pre_evaluated=pre_evaluated_for_page6,
                displayed_urls_today=page6_other_pages_urls or None,
            )
            books_t = page_six_telemetry["books"]
            music_t = page_six_telemetry["music"]
            outdoor_t = page_six_telemetry["outdoor"]
            cooking_t = page_six_telemetry["cooking"]
            total_p6 = (
                books_t["cost_usd"] + music_t["cost_usd"]
                + outdoor_t["cost_usd"] + cooking_t["cost_usd"]
            )
            print(
                f"  Page VI: books={'✓' if not books_t['is_fallback'] else 'fallback'}, "
                f"music={'✓' if not music_t['is_fallback'] else 'fallback'}, "
                f"outdoor={'✓' if not outdoor_t['is_fallback'] else 'fallback'}, "
                f"cooking={'✓' if not cooking_t['is_fallback'] else 'fallback'}, "
                f"cost=${total_p6:.4f}",
                file=sys.stderr,
            )
        except Exception as e:
            print(
                f"[page6] FAILED: {type(e).__name__}: {e} — skipping Page VI regen",
                file=sys.stderr,
            )
            page_six_html = None

    # 4e) Editorial postscript (Sprint 4 Phase 3) — depends on all pages above.
    editorial_result: dict | None = None
    if not args.skip_editorial:
        # C45 D2 (Sprint 8, 2026-05-29) → C155 (Sprint 13, 2026-08-10) で恒久化。
        # v2 page1 パイプライン廃止により Page I は常に v3 essay（または休載
        # プレースホルダ）となり、v2 の top4 記事はそもそも存在しない。
        # よって editorial context の page_one は常に None。
        ctx = editorial_context.build_editorial_context(
            page_one_selected=None,
            page_two_selections=(
                page2_result.selections if page2_result is not None else None
            ),
            page_three_selections=(
                page3_result.selections if page3_result is not None else None
            ),
            page_four_telemetry=page_four_telemetry,
            page_five_telemetry=page_five_telemetry,
            page_six_telemetry=page_six_telemetry,
        )
        try:
            editorial_result = editorial_writer.write_editorial(ctx)
        except Exception as e:
            print(
                f"[editorial] FAILED (unhandled): {type(e).__name__}: {e}",
                file=sys.stderr,
            )
            editorial_result = {"body": "", "is_fallback": True, "cost_usd": 0.0}

    # 5) Render Page I placeholder + Page II + Page III
    # C155: Page I の中身は regen_front_page_v3 が組む。ここでは v3 が
    # surgical swap する対象の marker section だけを置く。月次選定未投入週は
    # このプレースホルダがそのまま紙面に残る（フェイルセーフ）。
    print("Building Page I placeholder (v3 swap target)...", file=sys.stderr)
    page_one_html = build_page_one_placeholder(target_date=target)
    page_two_html: str | None = None
    if page2_result is not None:
        print("Building Page II HTML...", file=sys.stderr)
        page_two_html = build_page_two_v2(page2_result.selections)
    page_three_html: str | None = None
    if page3_result is not None:
        print("Building Page III HTML...", file=sys.stderr)
        page_three_html = build_page_three_v2(page3_result.selections)

    # 6) Load template, update dates, swap Page I (and II + III + IV + V + VI), write
    print(f"Loading template: {TEMPLATE_PATH}", file=sys.stderr)
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    dated = update_template_date_strings(template, target)
    # Sprint 6: 全面共通のリンクスタイル（color inherit + dotted underline）。
    dated = inject_link_style_css(dated)
    # Sprint 5 task #2: masthead-data の CSS は常に inject。
    dated = inject_masthead_data_css(dated)
    # C155: Page I の CSS は v3 (inject_page_one_v3_css) が担当。v2 が出すのは
    # プレースホルダのみで、専用 CSS は不要。
    if page_two_html is not None:
        dated = inject_page_two_css(dated)
    if page_four_html is not None:
        dated = inject_page_four_css(dated)
    if page_five_html is not None:
        dated = inject_page_five_css(dated)
    if page_six_html is not None:
        dated = inject_page_six_css(dated)
    # Sprint 4 Phase 3: 編集後記の CSS は常に inject（idempotent、guarded by marker）。
    # is_fallback=True の日は HTML 自体が出ないため、CSS は遊休状態で残るが副作用なし。
    dated = inject_editorial_css(dated)
    final_html = replace_page_one(dated, page_one_html)
    if page_two_html is not None:
        final_html = replace_page_two(final_html, page_two_html)
    if page_three_html is not None:
        final_html = replace_page_three(final_html, page_three_html)
    if page_four_html is not None:
        final_html = replace_page_four(final_html, page_four_html)
    if page_five_html is not None:
        final_html = replace_page_five(final_html, page_five_html)
    if page_six_html is not None:
        final_html = replace_page_six(final_html, page_six_html)
    # Sprint 5 task #2: masthead-data 2-row block で <div class="strip"> を置換。
    # 全 fetch が失敗した場合は build_header_html() が "" を返し、no-op。
    print("Building masthead-data...", file=sys.stderr)
    try:
        masthead_data_html = header_module.build_header_html(today=target)
    except Exception as e:
        print(
            f"[masthead-data] FAILED (unhandled): {type(e).__name__}: {e}",
            file=sys.stderr,
        )
        masthead_data_html = ""
    final_html = replace_strip_with_masthead_data(final_html, masthead_data_html)
    # Sprint 4 Phase 3: 編集後記を <footer class="colophon"> の直前に挿入。
    # is_fallback=True なら footer_html="" で no-op、紙面は Page VI で終わる。
    if editorial_result is not None:
        editorial_footer_html = _render_editorial_footer(editorial_result, target_date=target)
        final_html = insert_editorial_footer(final_html, editorial_footer_html)

    out_path = _archive_path(target)
    if out_path.exists():
        print(f"Overwriting existing {out_path}", file=sys.stderr)
    out_path.write_text(final_html, encoding="utf-8")
    print(f"Wrote {out_path}", file=sys.stderr)

    # 7) Sprint 2/3: record displayed URLs for tomorrow's dedup.
    # C155: page1 は v3 essay（週次主軸記事、月次人手選定）なので日次 URL dedup
    # の対象外。空リストを渡して log の page1 フィールドは維持する（過去日 log の
    # スキーマ互換のため。load_recently_displayed_urls(page="page1") は空を返す）。
    page1_urls_displayed: list[str] = []
    page2_urls_displayed: dict[str, str | None] = {k: None for k in PAGE2_COMPANY_ORDER}
    if page2_result is not None:
        for company_key in PAGE2_COMPANY_ORDER:
            sel = page2_result.selections.get(company_key)
            if sel is not None and sel.article is not None:
                page2_urls_displayed[company_key] = sel.article.get("url")
    page3_urls_displayed: list[str | None] = []
    if page3_result is not None:
        for region in PAGE3_DISPLAY_SLOTS:
            sel = page3_result.selections.get(region)
            if sel is not None and sel.article is not None:
                page3_urls_displayed.append(sel.article.get("url"))
            else:
                page3_urls_displayed.append(None)
    # C155: Page IV は「今日の概念」のみで外部記事を持たないため、
    # displayed_urls への記録対象がなくなった（page4_urls は常に空）。
    page4_urls_displayed: list[str] = []
    # C155: 第5面の serendipity 枠は Page III へ移設。第5面が持つ記事は
    # 「一筆の参照記事」1 本で、これは Page III 由来（確定枠 or runner-up）の
    # ため page3_urls 側で既に記録済み。二重記録を避けるため page5_url は
    # 一筆の参照記事が runner-up 由来だった場合のみ記録する。
    page5_url_displayed: str | None = None
    if page_five_telemetry is not None:
        ai_art5 = page_five_telemetry.get("ai_article")
        if ai_art5 and ai_art5.get("url"):
            url5 = ai_art5["url"]
            if url5 not in [u for u in page3_urls_displayed if u]:
                page5_url_displayed = url5
    page6_urls_displayed: dict[str, str | None] = {}
    if page_six_telemetry is not None:
        for area in ("books", "music", "outdoor"):
            r = page_six_telemetry.get(area, {})
            art = r.get("article")
            page6_urls_displayed[area] = art.get("url") if art else None
    # C155: Today's Headlines 廃止に伴い headlines_urls は常に None。
    # 過去日 log には headlines フィールドが残るため、読み出し側
    # (load_recently_displayed_urls(page="headlines")) は引き続き動作する。
    log_path = write_displayed_urls_log(
        target,
        page1_urls=page1_urls_displayed,
        page2_urls_by_company=page2_urls_displayed,
        page3_urls=page3_urls_displayed if page3_result is not None else None,
        page4_urls=None,  # C155: Page IV は外部記事を持たない
        page5_url=page5_url_displayed,
        page6_urls=page6_urls_displayed if page_six_telemetry is not None else None,
        headlines_urls=None,
    )
    print(f"Wrote {log_path}", file=sys.stderr)

    # 6) Optional index update
    if args.update_index:
        update_index_redirect(target)
    else:
        print("(index.html not touched; pass --update-index to rewrite redirect)", file=sys.stderr)

    print()
    print("=== Page I ===")
    print("  v3 (regen_front_page_v3) が essay を swap する。本 module は"
          "プレースホルダのみ出力。")

    if page2_result is not None:
        print()
        print("=== Page II summary ===")
        for company_key in PAGE2_COMPANY_ORDER:
            sel = page2_result.selections.get(company_key)
            display, _ = COMPANY_DISPLAY_META[company_key]
            if sel is None or sel.article is None:
                print(f"  [{display:<14}] 本日休載  (stage={sel.stage_used if sel else 'none'})")
                continue
            print(
                f"  [{display:<14}] stage={sel.stage_used:<14} "
                f"score={sel.page2_final_score:6.2f}  "
                f"({sel.article.get('source_name', '')[:25]})"
            )
            print(f"      title: {sel.article.get('title_ja', '')[:60]}")
            print(f"      問い:  {sel.morning_question}")
        print(f"  cost (Page II Step 1+2 LLM): ${page2_result.cost_usd:.4f}")

    if page3_result is not None:
        print()
        print("=== Page III summary ===")
        for region in PAGE3_DISPLAY_SLOTS:
            sel = page3_result.selections.get(region)
            display = PAGE3_REGION_DISPLAY_NAMES[region]
            if sel is None or sel.article is None:
                # C170 (2026-08-18): ここだけ fallback_reason を落としていた。
                # 他の空枠ログ（Page III selections / Page VI）は理由を出しており、
                # 本番経路で出るのはこの summary なので、R3 の placeholder が
                # 8 月に 3 回起きても原因が追えなかった（C156 の教訓の適用漏れ）。
                reason = sel.fallback_reason if sel else "no entry"
                print(f"  [{region} {display:<18}] 本日該当なし  ({reason})")
                if sel is not None and sel.fallback_detail:
                    print(f"      理由: {sel.fallback_detail}")
                continue
            art = sel.article
            kicker = _page3_generate_kicker(art, region)
            print(
                f"  [{region} {display:<18}] score={sel.final_score:6.2f}  "
                f"kicker={kicker:<14}  ({art.get('source_name', '')[:25]})"
            )
            print(f"      title: {art.get('title', '')[:70]}")
        print(f"  cost (Page III Stage 2 LLM): ${page3_result.cost_usd:.4f}")
        if page3_result.placeholder_count >= 2:
            print(
                f"  ⚠ {page3_result.placeholder_count} 領域 placeholder "
                "（2 領域以上）— 詳細は GHA artifact audit-logs-<日付> 内の "
                "logs/page3_selection_*.json（.gitignore 済みで repo には無い、"
                "retention 90 日）"
            )

    if page_four_telemetry is not None:
        print()
        print("=== Page IV summary ===")
        c = page_four_telemetry["concept"]
        e = page_four_telemetry["essay_result"]
        print(f"  Concept of the Week: {c['id']}  ({c['name_ja']} / {c['name_en']})")
        print(f"    domain: {c['domain']}, difficulty: {c['difficulty']}")
        print(f"    essay length: {len(e['essay'])} chars, "
              f"fallback: {e['is_fallback']}, cost: ${e['cost_usd']:.4f}")

    if page_five_telemetry is not None:
        print()
        print("=== Page V summary ===")
        art5 = page_five_telemetry.get("ai_article")
        col5 = page_five_telemetry.get("column")
        sum5 = page_five_telemetry.get("summary")
        if art5 is None:
            print("  PLACEHOLDER (一筆の対象記事が候補ゼロ)")
        else:
            print(f"  参照記事   : {art5.get('source_name', '')[:30]}")
            print(f"  title      : {art5.get('title', '')[:70]}")
            if sum5 is not None:
                tag = "(fallback)" if sum5["is_fallback"] else "(LLM)"
                print(f"  サマリ     : {len(sum5['summary'])}字 {tag}  "
                      f"cost=${sum5.get('cost_usd', 0.0):.4f}")
            if col5 is not None:
                tag = "(fallback)" if col5["is_fallback"] else f"({col5['elapsed_ms']}ms)"
                print(f"  一筆       : {col5['column_title']} {tag}")
                print(f"  body[:60]  : {col5['column_body'][:60]}")
        print("  miibo API cost: 別系統（神山さんの会社契約定額枠内）")

    if page_six_telemetry is not None:
        print()
        print("=== Page VI summary ===")
        total_p6 = 0.0
        for area_key, area_label in (
            ("books", "読書"), ("music", "音楽"), ("outdoor", "アウトドア"),
        ):
            r = page_six_telemetry[area_key]
            total_p6 += r["cost_usd"]
            if r["article"] is None:
                print(f"  [{area_label:<8}] 本日該当なし  ({r.get('fallback_reason', '')})")
                continue
            art = r["article"]
            score = art.get("final_score", 0.0)
            fallback_tag = " (fallback)" if r["is_fallback"] else ""
            print(
                f"  [{area_label:<8}] score={score:6.2f}  "
                f"({art.get('source_name', '')[:25]}){fallback_tag}"
            )
            print(f"      title  : {art.get('title', '')[:70]}")
            print(f"      column : {r['column_title'][:30]}")
            print(f"      body   : {r['column_body'][:50]}...")
        c = page_six_telemetry["cooking"]
        total_p6 += c["cost_usd"]
        cook_tag = " (fallback)" if c["is_fallback"] else ""
        print(f"  [{'料理':<8}] {c['dish_name']} ({c['genre']}){cook_tag}")
        print(f"      ingredients: {c['ingredients_summary']}")
        print(f"      column : {c['column_title']}")
        print(f"      body   : {c['column_body'][:50]}...")
        print(f"  cost (Page VI LLM 4 calls): ${total_p6:.4f}")

    print(f"  output: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
