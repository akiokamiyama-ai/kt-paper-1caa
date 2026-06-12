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

import argparse
import html
import re
import sys
import time
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timezone, timedelta
from pathlib import Path
from typing import Iterable

from .fetch import run as fetch_run
from .lib.source import Article
from .render import replace_page_one
from .selector.stage1 import run_stage1
from .selector.stage2 import run_stage2
from .selector.stage3 import integrate_scores
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
from .selector import todays_headlines
from .selector.page3 import (
    REGIONS as PAGE3_REGIONS,
    REGION_DISPLAY_NAMES as PAGE3_REGION_DISPLAY_NAMES,
    _generate_kicker as _page3_generate_kicker,
    _is_japanese_source as _page3_is_japanese_source,
    run_page3_pipeline,
)
from .selector.why_important import (
    LLMError as WhyImportantLLMError,
    ValidationError as WhyImportantValidationError,
    generate_why_important,
    static_why_important,
)
from .editorial import context_builder as editorial_context
from .editorial import editorial_writer
from .header import header_builder as header_module
from .page1_v3.monthly_pivotal import (
    DEFAULT_PIVOTAL_PATH,
    find_week_for_date,
    load_monthly_pivotal,
)
from .page1 import lead_deck_writer as page1_lead_deck
from .page4 import article_rotator as page4_rotator
from .page4 import concept_selector as page4_concept_selector
from .page4 import concept_writer as page4_concept_writer
from .page5 import ai_kamiyama_writer as page5_ai_kamiyama
from .page5 import serendipity_selector as page5_serendipity
from .page6 import cooking_generator as page6_cooking
from .page6 import leisure_recommender as page6_leisure
from .lib.llm import CapExceededError
from .translate import translate

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ARCHIVE_DIR = PROJECT_ROOT / "archive"
TEMPLATE_PATH = ARCHIVE_DIR / "2026-04-25.html"
INDEX_HTML = PROJECT_ROOT / "index.html"

# C81 段階 1 (Sprint 9, 2026-06-13, Fable review M6): SOURCE_NAME_FILTERS は
# ``scripts/source_allowlist.py`` に移動。todays_headlines.HEADLINES_ALLOWED_SOURCES
# と単一 module で同期管理することで C78 真因（片側更新漏れ）を構造的に予防。
# 旧名で本 module から import している外部コードのため re-export を残す。
from .source_allowlist import SOURCE_NAME_FILTERS  # noqa: F401  re-export

# Sources whose articles are already in Japanese — translation is skipped.
JAPANESE_SOURCE_PATTERNS: tuple[str, ...] = (
    "Foresight",
    "Forbes Japan",
    "ZDNet Japan",
    "ITmedia",
    "PR TIMES",
)

# Sprint 2 Step B 期間中の page2.run_page2_pipeline 呼び出し時の運用 threshold。
# scripts/selector/page2.py の DEFAULT_THRESHOLD = 40.0 を caller 側で
# override する形（page2.py のモジュール定数は不変）。
PAGE2_THRESHOLD = 35.0

# Sprint 2 Step D: 重複排除レイヤー。displayed_urls_*.json を遡及参照して
# 過去 N 日に「実際に紙面で表示した」記事を翌朝以降の選定から除外する。
PAGE1_DEDUP_DAYS = 7
PAGE2_DEDUP_DAYS = 3

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

# Front page composition.
N_TOP = 1
N_SECONDARIES = 3
PER_SOURCE_LIMIT = 8  # cap per source so a chatty feed cannot dominate Stage 2

# Translation pacing.
TRANSLATE_DELAY = 0.3

# ---------------------------------------------------------------------------
# Page I source-based soft penalties (Sprint 6, 2026-05-03)
# ---------------------------------------------------------------------------
# 神山さんが既に有料購読しており、いずれ必ず読む媒体は Tribune が再露出する
# 価値が低い。第1面選定で final_score 計算後に減点する形で頻出を抑制する。
#
# 適用範囲：第1面（``run_pipeline``）のみ。Page IV academic / Page V serendipity /
# Page VI leisure は別の選定経路を通り、本 penalty の影響を受けない。
#
# Sprint 5 ポストモーメント (2026-05-04): -5 では Foresight が第1面 TOP に
# 出ることが 5/4 archive で実証された（"UAE OPEC 離脱" 38.30 で TOP）。
# 30 日観察を待たず -10 に強化、約 26% 削減効果（スケール 31-38 に対して）。
#
# 30 日運用後の観察ポイント（-10 強化済み）：
#   - 第1面の Foresight 出現頻度（logs/scores_*.json と displayed_urls_*.json から集計）
#   - 出現頻度が依然として高い場合：penalty を -15 に強化、または B3
#     （sources/*.md に penalty フィールド追加）への移行検討
#   - Foresight 以外の媒体も減点したくなった場合も B3 拡張で対応
FORESIGHT_PENALTY: float = -10.0
FORESIGHT_PATTERNS: tuple[str, ...] = ("Foresight",)

# C42 案A (Sprint 9, 2026-06-04): 旧 Foresight 後継として導入された新潮QUE。
# 神山さんは QUE 有料会員。Foresight と同種の購読中媒体。
#
# 履歴：
# - 6/4 初期値 -5.0（Foresight -10 より弱め、初動観察用）
# - 6/5 W2 Day 6 朝刊で QUE 採用 0 件 → -5.0 が効きすぎと判定、神山さん指示で
#   いったん 0.0 に外して様子見（C42 ペナルティ調整、6/5 → 6/6 cron 反映）。
#   1 週間運用観察後に再調整判断する
# - 将来：QUE が紙面占有過剰なら -3 / -5 / -10 に再強化、Foresight 在庫枯渇後の
#   バランス次第
SHINCHO_QUE_PENALTY: float = 0.0
SHINCHO_QUE_PATTERNS: tuple[str, ...] = ("Shincho QUE", "新潮QUE")


def _apply_page1_source_penalty(article: dict) -> float:
    """Return the Page-I-only soft penalty for an article based on source name.

    Returns 0.0 when no penalty applies. 神山さん購読中の媒体（Foresight /
    新潮QUE）に対して、Page I 過剰露出を抑制する soft penalty。順序：
    Foresight → Shincho QUE → no-op。Other paid-subscription sources (HBR /
    WSJ / FT / 日経 等) は据え置き。
    """
    source_name = article.get("source_name", "") or ""
    for pattern in FORESIGHT_PATTERNS:
        if pattern in source_name:
            return FORESIGHT_PENALTY
    for pattern in SHINCHO_QUE_PATTERNS:
        if pattern in source_name:
            return SHINCHO_QUE_PENALTY
    return 0.0

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
# Result type
# ---------------------------------------------------------------------------

@dataclass
class PipelineResult:
    fetched_by_source: dict[str, int]
    fetched_total: int
    stage1_passed: int
    stage1_excluded: int
    stage2_evaluated: int
    stage2_errors: int
    stage2_cost_usd: float
    selected: list[dict]
    candidates_scored: list[dict]


# ---------------------------------------------------------------------------
# Article preparation
# ---------------------------------------------------------------------------

def _strip_html(text: str | None) -> str:
    """Remove HTML tags and collapse whitespace. Keeps Japanese punctuation."""
    if not text:
        return ""
    no_tags = _HTML_TAG_RE.sub(" ", text)
    no_entities = (
        no_tags
        .replace("&nbsp;", " ")
        .replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
    )
    return _WHITESPACE_RE.sub(" ", no_entities).strip()


def _is_japanese_source(source_name: str | None) -> bool:
    """Detect whether a source's content is Japanese (so translation is skipped).

    Uses two signals:
    1. Substring match against ``JAPANESE_SOURCE_PATTERNS`` (covers EN-named
       JA sources like "Forbes Japan", "ZDNet Japan", "ITmedia AI＋").
    2. Heuristic: source name contains ≥2 hiragana / katakana / kanji
       characters (covers "経済産業省ニュースリリース", "日本の人事部 プロネット",
       "ビジネスチャンス", "DIAMONDハーバード・ビジネス・レビュー", etc.).

    EN-only sources (HBR.org, MIT Sloan, Aeon, BBC, Economist) match neither
    and fall through to translation.
    """
    if not source_name:
        return False
    if any(pat in source_name for pat in JAPANESE_SOURCE_PATTERNS):
        return True
    # Strip parenthetical metadata like "Foresight（新潮社）" or
    # "Harvard Business Review（HBR.org）" — these annotations contain JA chars
    # but the actual content language is determined by the rest of the name.
    name_stripped = re.sub(r"[（(][^）)]*[）)]", "", source_name)
    ja_chars = sum(
        1 for c in name_stripped
        if "぀" <= c <= "ゟ"   # hiragana
        or "゠" <= c <= "ヿ"   # katakana
        or "一" <= c <= "鿿"   # kanji
    )
    return ja_chars >= 2


def _kicker_for(source_name: str | None, *, is_top: bool) -> str:
    if not source_name:
        return DEFAULT_KICKER
    for prefix, kicker in KICKER_PREFIXES:
        if prefix in source_name:
            return f"{kicker}・トップ" if is_top else kicker
    return DEFAULT_KICKER


# Sprint 2 Step E: 記事の発行日表示。byline に「· 2026年4月28日」を追記する。
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


def _byline_for(source_name: str | None) -> str:
    if not source_name:
        return "本紙編集部"
    label = "外部ソース"
    for prefix, kicker in KICKER_PREFIXES:
        if prefix in source_name:
            label = kicker.split("・")[0]  # strip "・国際情勢" subtitle if present
            break
    return f"本紙編集部　{label}より構成"


def _article_to_pipeline_dict(article: Article) -> dict:
    """Convert a fetched Article into the dict shape Stage 1+2+rendering expect.

    C80c (Sprint 9, 2026-06-12, Fable review M1): pipeline_dict 構築は
    ``Article.to_pipeline_dict()`` に一本化（page1 / page3 / stage1 で同一実装
    を共有、tribune_category 伝播も一括）。本関数は page1 固有の
    ``_strip_html`` 適用のみ担当する薄いラッパー。
    """
    desc_clean = _strip_html(article.description)
    body_clean = _strip_html(
        "\n".join(article.body_paragraphs) if article.body_paragraphs else ""
    )
    return article.to_pipeline_dict(description=desc_clean, body=body_clean)


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

def fetch_candidates(
    *,
    per_source_limit: int = PER_SOURCE_LIMIT,
    no_dedupe: bool = True,
) -> tuple[list[Article], dict[str, int]]:
    """Fetch articles from each configured source.

    Returns (articles, per_source_counts). per_source_counts uses the
    user-friendly source-filter token (e.g. ``"BBC Business"``) as key.
    """
    all_articles: list[Article] = []
    per_source: dict[str, int] = {}
    for filt in SOURCE_NAME_FILTERS:
        summary = fetch_run(
            name_substring=filt,
            limit=per_source_limit,
            no_dedupe=no_dedupe,
            write_log=False,
            # C42 fix (Sprint 9, 2026-06-08): fetch.py:run のデフォルトは
            # include_html=False で fetch_method=HTML の source を全部除外する
            # ため、新潮 QUE のような HTML scraper source が候補プールに
            # 一切到達できない。Page I は name_substring filter で動くので
            # 本配列 (SOURCE_NAME_FILTERS) に該当する HTML scraper source の
            # 場合のみ効果を持つ（現状は無いが将来の整合性のため有効化）。
            include_html=True,
        )
        articles = summary.get("articles", [])
        per_source[filt] = len(articles)
        all_articles.extend(articles)
    return all_articles, per_source


def run_pipeline(
    articles: Iterable[Article],
) -> PipelineResult:
    """Run Stage 1 → 2 → 3 over fetched articles. Returns a PipelineResult.

    No I/O side effects beyond the Stage 2 LLM call and its log writes
    (logs/scores_*.json, logs/llm_usage_*.json).
    """
    articles = list(articles)
    pipeline_dicts = [_article_to_pipeline_dict(a) for a in articles]

    s1_out = run_stage1(pipeline_dicts)
    surviving = [a for a in s1_out if not a.get("is_excluded")]
    excluded_count = len(s1_out) - len(surviving)

    if not surviving:
        return PipelineResult(
            fetched_by_source={},
            fetched_total=len(articles),
            stage1_passed=0,
            stage1_excluded=excluded_count,
            stage2_evaluated=0,
            stage2_errors=0,
            stage2_cost_usd=0.0,
            selected=[],
            candidates_scored=[],
        )

    s2 = run_stage2(surviving)

    # Stage 3 — in-place fill final_score on the Stage-2 entry dict.
    integrate_scores(s2.evaluations_by_url)

    # Merge LLM scores + final_score back into the surviving article dicts
    # so the renderer has both rendering fields and scoring fields together.
    by_url = s2.evaluations_by_url
    scored: list[dict] = []
    for art in surviving:
        url = art.get("url")
        if url and url in by_url:
            art.update(by_url[url])
            scored.append(art)
    # Sprint 6 (2026-05-03): Page I source-based soft penalty。
    # final_score sort の直前で source_name に基づく減点を適用。
    # 神山さんが既に購読中の媒体（Foresight）の頻出抑制。
    for art in scored:
        penalty = _apply_page1_source_penalty(art)
        if penalty != 0.0:
            original_score = float(art.get("final_score", 0.0))
            new_score = round(original_score + penalty, 2)
            art["final_score"] = new_score
            art["page1_source_penalty"] = penalty
            print(
                f"  [page1] source penalty: "
                f"{(art.get('source_name') or '')[:30]} "
                f"({original_score:.2f} → {new_score:.2f}, {penalty:+.1f})  "
                f"{(art.get('title') or '')[:40]}",
                file=sys.stderr,
            )
    scored.sort(key=lambda a: a.get("final_score", 0.0), reverse=True)

    return PipelineResult(
        fetched_by_source={},
        fetched_total=len(articles),
        stage1_passed=len(surviving),
        stage1_excluded=excluded_count,
        stage2_evaluated=len(s2.evaluations_by_url),
        stage2_errors=len(s2.errors),
        stage2_cost_usd=s2.cost_usd,
        selected=scored[: N_TOP + N_SECONDARIES],
        candidates_scored=scored,
    )


# ---------------------------------------------------------------------------
# Translation
# ---------------------------------------------------------------------------

def _is_japanese_article(article: dict) -> bool:
    """記事の言語判定。primary signal は Article.source_language（Sprint 5、
    sources/*.md の language: ja|en に基づき drivers から伝播）。

    source_language キーが存在しない場合（page2 経路など、まだ伝播路が
    通っていない経路の article dict 等）は _is_japanese_source heuristic に
    フォールバックする。RSS 仕様変更や source 未タグ漏れの保険も兼ねる。
    """
    sl = article.get("source_language")
    if sl == "en":
        return False
    if sl == "ja":
        return True
    # source_language キー無し or 不正値 → heuristic にフォールバック
    return _is_japanese_source(article.get("source_name", ""))


def _translate_article(article: dict) -> None:
    """Populate ``title_ja`` / ``desc_ja`` in-place.

    翻訳ポリシー Sprint 5 で「タイトルのみ翻訳」に変更（2026-05-03）。
    本文（description）は原文のまま desc_ja に代入する。

    本文翻訳を復活させる場合：
      1. ↓ ブロックコメントを解除（下の `# desc_ja = translate(desc)` 等）
      2. その下の `desc_ja = desc  # passthrough (Sprint 5)` 行を削除
      3. ``translate_for_render`` のログメッセージ "(title only)" を戻す
      4. テスト ``test_translate_*_passthrough_desc`` を更新
    """
    if _is_japanese_article(article):
        article["title_ja"] = article.get("title", "")
        article["desc_ja"] = article.get("description", "")
        return
    title = article.get("title", "") or ""
    desc = article.get("description", "") or ""
    title_ja = translate(title) if title else ""
    time.sleep(TRANSLATE_DELAY)
    # --- Sprint 5 (2026-05-03): 本文翻訳を停止、原文 passthrough ---
    # desc_ja = translate(desc) if desc else ""
    # time.sleep(TRANSLATE_DELAY)
    desc_ja = desc  # passthrough (Sprint 5)
    # --- end Sprint 5 ---
    article["title_ja"] = title_ja or title
    article["desc_ja"] = desc_ja or desc


def translate_for_render(articles: list[dict]) -> None:
    """Add title_ja (translated) and desc_ja (= description passthrough) to each article.

    Sprint 5 (2026-05-03): タイトルのみ翻訳、本文は原文 passthrough。
    """
    for i, a in enumerate(articles):
        is_ja = _is_japanese_article(a)
        if is_ja:
            marker = " (JA passthrough)"
        else:
            marker = " (title only)"
        print(
            f"  [{i+1}] translating: {a.get('title', '')[:60]}{marker}",
            file=sys.stderr,
        )
        _translate_article(a)


# ---------------------------------------------------------------------------
# Rendering — source-aware Page I builder
# ---------------------------------------------------------------------------

# Sprint 5 task #2 (2026-05-04): masthead-data 2-row block の CSS。
# 既存の <div class="strip">（4/25 template ダミー）を置換する形で挿入。
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


# Sprint 5 (2026-05-03): 第1面の HTML 表示形式を「原文タイトル大 + 日本語小書き」に
# 変更（選択肢 C）。CSS は inject_page_one_css でテンプレ </style> 直前に挿入。
PAGE_ONE_CSS_MARKER = "/* === Page I title formatting (Sprint 5, 2026-05-03) === */"

PAGE_ONE_CSS = f"""
{PAGE_ONE_CSS_MARKER}
.article-title-original {{
  font-family: 'Noto Serif JP', 'Times New Roman', serif;
  font-size: 22px;
  font-weight: 700;
  line-height: 1.3;
  margin: 0 0 6px;
}}
.article-title-japanese {{
  font-family: 'Noto Serif JP', serif;
  font-size: 13px;
  font-weight: 400;
  color: #666;
  line-height: 1.5;
  margin: 0 0 12px;
  padding-left: 2px;
}}
/* Top の lead-story では h2.headline-xl をそのまま original 用に流用、サイズだけ拡張 */
.lead-story h2.article-title-original {{
  font-size: 36px;
  line-height: 1.2;
}}
.secondaries .col h3.article-title-original {{
  font-size: 20px;
}}
"""


def inject_page_one_css(html_text: str) -> str:
    """Idempotently inject Page I title CSS just before </style>."""
    if PAGE_ONE_CSS_MARKER in html_text:
        return html_text
    end_style_idx = html_text.rfind("</style>")
    if end_style_idx < 0:
        head_close = html_text.find("</head>")
        if head_close < 0:
            return html_text
        injected = f"<style>\n{PAGE_ONE_CSS}\n</style>\n"
        return html_text[:head_close] + injected + html_text[head_close:]
    return html_text[:end_style_idx] + PAGE_ONE_CSS + html_text[end_style_idx:]


def _esc(s: str) -> str:
    return html.escape(s or "")


def _render_top_body(top: dict) -> str:
    """Single-paragraph dropcap from desc_ja + a source byline.

    Sprint 6: byline を「出典：{label}」(plain text) に変更。タイトル h2 が
    <a href> で URL を持つため、byline には URL リンクを置かない（重複回避）。
    """
    desc_ja = top.get("desc_ja", "") or top.get("description", "")
    paragraphs = [f'<p class="dropcap">{_esc(desc_ja)}</p>']
    source_name = top.get("source_name", "") or "外部ソース"
    label = source_name
    for prefix, kicker in KICKER_PREFIXES:
        if prefix in source_name:
            label = kicker.split("・")[0]
            break
    paragraphs.append(
        f'<p class="byline" style="margin-top:8px;">出典：{_esc(label)}</p>'
    )
    return "\n".join("          " + p for p in paragraphs)


def _render_secondary_body(sec: dict) -> str:
    desc_ja = sec.get("desc_ja", "") or sec.get("description", "")
    source_name = sec.get("source_name", "") or "外部ソース"
    label = source_name
    for prefix, kicker in KICKER_PREFIXES:
        if prefix in source_name:
            label = kicker.split("・")[0]
            break
    paragraphs = [f"        <p>{_esc(desc_ja)}</p>"]
    paragraphs.append(
        f'        <p class="byline" style="margin-top:6px;">出典：{_esc(label)}</p>'
    )
    return "\n".join(paragraphs)


def _build_sidebar(top: dict) -> str:
    """The 'なぜ重要か' sidebar — LLM-generated 3 points with static fallback.

    Sprint 2 後半 / Sprint 3: docs/why_important_v1.md §6.3 の設計に従い、
    トップ記事の主題・重要論点・経営者視点 3点を Sonnet 4.6 で動的生成。
    LLM 障害・validation 失敗・cap 抵触時は static_why_important() の
    定型文にフォールバック（神山さんの第1面読書体験は最低限保証）。
    """
    try:
        points = generate_why_important(top)
    except (
        WhyImportantLLMError,
        WhyImportantValidationError,
        CapExceededError,
    ) as e:
        print(
            f"[sidebar] LLM failed, using static fallback: {e}",
            file=sys.stderr,
        )
        points = static_why_important(top)
    return _render_sidebar_html(top, points)


def _render_sidebar_html(top: dict, points: dict) -> str:
    """Render the lead-sidebar HTML from a 3-point dict.

    Layout follows archive/2026-04-25.html's <aside class="lead-sidebar">.
    Points dict keys: point_1_subject / point_2_significance /
    point_3_executive_perspective.
    """
    p1 = _esc(points.get("point_1_subject", ""))
    p2 = _esc(points.get("point_2_significance", ""))
    p3 = _esc(points.get("point_3_executive_perspective", ""))
    return f"""
      <aside class="lead-sidebar" lang="ja">
        <div class="kicker">なぜ重要か</div>
        <h4 class="headline-m">本日のトップから読み取るべきこと</h4>
        <p>読み解きのための3点：</p>
        <hr class="dotted" />
        <p><strong>1・</strong>{p1}</p>
        <p><strong>2・</strong>{p2}</p>
        <p><strong>3・</strong>{p3}</p>
        <hr class="dotted" />
        <p class="byline" style="margin-top:8px;">出典：3ソース合議 · 翻訳：Google／MyMemory（日本語ソースは原文）</p>
      </aside>""".rstrip()


def build_page_one_v2(
    articles: list[dict], *, target_date: date | None = None,
) -> str:
    """Assemble the full <section class='page page-one'> block."""
    if len(articles) < N_TOP + N_SECONDARIES:
        raise ValueError(
            f"need {N_TOP + N_SECONDARIES} articles, got {len(articles)}"
        )
    top = articles[0]
    secs = articles[1 : N_TOP + N_SECONDARIES]

    secondaries_html: list[str] = []
    for s in secs:
        kicker = _kicker_for(s.get("source_name"), is_top=False)
        byline = _byline_for(s.get("source_name"))
        date_label = _format_publish_date_ja(s.get("pub_date"))
        if date_label:
            byline = f"{byline} · {date_label}"
        # Sprint 5: 原文タイトル大 + 日本語小書き。JA ソースは title_ja=title なので
        # 二重表示を避けて jp タイトル行を出さない。
        s_title_orig = s.get("title", "")
        s_title_ja = s.get("title_ja", "")
        s_is_ja = _is_japanese_article(s)
        s_jp_line = (
            "" if s_is_ja
            else f'\n        <p class="article-title-japanese">{_esc(s_title_ja)}</p>'
        )
        # Sprint 6: タイトルにリンク。URL があれば <a> で囲む。
        s_url = s.get("url", "")
        s_title_html = (
            f'<a href="{_esc(s_url)}" target="_blank" rel="noopener noreferrer">{_esc(s_title_orig)}</a>'
            if s_url else _esc(s_title_orig)
        )
        secondaries_html.append(
            f"""
      <div class="col" lang="ja">
        <div class="kicker">{_esc(kicker)}</div>
        <h3 class="headline-l article-title-original">{s_title_html}</h3>{s_jp_line}
        <p class="byline">{_esc(byline)}</p>
{_render_secondary_body(s)}
      </div>""".rstrip()
        )

    top_kicker = _kicker_for(top.get("source_name"), is_top=True)
    top_byline = _byline_for(top.get("source_name"))
    top_date_label = _format_publish_date_ja(top.get("pub_date"))
    if top_date_label:
        top_byline = f"{top_byline} · {top_date_label}"

    # Sprint 5: top の表示も原文大 + 日本語小書き。
    top_title_orig = top.get("title", "")
    top_title_ja = top.get("title_ja", "")
    top_is_ja = _is_japanese_article(top)
    top_jp_line = (
        "" if top_is_ja
        else f'\n        <p class="article-title-japanese">{_esc(top_title_ja)}</p>'
    )
    # Sprint 6: top のタイトルにリンク。URL があれば <a> で囲む。
    top_url = top.get("url", "")
    top_title_html = (
        f'<a href="{_esc(top_url)}" target="_blank" rel="noopener noreferrer">{_esc(top_title_orig)}</a>'
        if top_url else _esc(top_title_orig)
    )

    # Sprint 5 task #3 (2026-05-04): top のリード deck を LLM 生成。
    # deck と dropcap が同じ desc_ja を表示していた重複を解消する。
    # deck = LLM が記事核心を 60-100 字に圧縮、dropcap は desc_ja のまま（本文）。
    # LLM 失敗時は desc_ja[:80] フォールバック。deck が空文字列なら <p> 自体を出さない。
    try:
        lead_deck_result = page1_lead_deck.write_lead_deck(top)
    except Exception as e:
        print(
            f"[lead_deck] FAILED (unhandled): {type(e).__name__}: {e}",
            file=sys.stderr,
        )
        lead_deck_result = {
            "deck": (top.get("desc_ja") or "")[:80],
            "is_fallback": True,
            "cost_usd": 0.0,
        }
    lead_deck = lead_deck_result.get("deck") or ""
    deck_line = (
        f'\n        <p class="deck">{_esc(lead_deck)}</p>'
        if lead_deck else ""
    )

    # C69 (Sprint 9, 2026-06-09): 1 面右下にコメント CTA。target_date が
    # 渡された場合のみ出力（旧 caller 後方互換）。
    cta_html = ""
    if target_date is not None:
        cta_html = "\n    " + render_page_one_comment_cta(target_date)

    page = f"""<section class="page page-one">
    <div class="page-banner"><span class="pg-num">— Page I —</span> The Front Page · World &amp; Business</div>

    <article class="front-top">
      <div class="lead-story" lang="ja">
        <div class="kicker">{_esc(top_kicker)}</div>
        <h2 class="headline-xl article-title-original">{top_title_html}</h2>{top_jp_line}{deck_line}
        <p class="byline">{_esc(top_byline)}</p>
        <div class="body-3col">
{_render_top_body(top)}
        </div>
      </div>
{_build_sidebar(top)}
    </article>

    <div class="secondaries">{"".join(secondaries_html)}
    </div>{cta_html}
  </section>"""

    return page


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

/* Sprint 7 Phase 2 (2026-05-19): 2 面下段 Today's Headlines。
   3 社の朝会セクションの下に、Page I/III 採用記事を除く許可ソース
   (NHK 主要/経済、Yahoo! 経済、BBC、Economist) から top 3 を掲載。 */
.todays-headlines {{
  margin-top: 32px;
  padding-top: 20px;
  border-top: 1px solid #ccc;
}}
.todays-headlines .headlines-banner {{
  font-family: 'Playfair Display', serif;
  font-size: 14px;
  text-transform: uppercase;
  letter-spacing: 0.15em;
  margin: 0 0 12px;
  text-align: center;
}}
.todays-headlines .headlines-list {{
  /* 5/20 神山さん観察 (C13): 新聞らしい 3 段組み。
     5/19 の縦 1 列は Code の誤解釈、横並びの段組みが本来の意図。 */
  list-style: none;
  padding: 0;
  margin: 0;
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 24px;
}}
.todays-headlines .headline-item {{
  margin-bottom: 0;
  padding-bottom: 0;
  border-bottom: none;
  border-right: 1px solid #ccc;
  padding-right: 24px;
}}
.todays-headlines .headline-item:last-child {{
  border-right: none;
  padding-right: 0;
}}
@media (max-width: 768px) {{
  /* 媒体特性: スマホでは段組みを解いて縦並び。 */
  .todays-headlines .headlines-list {{
    grid-template-columns: 1fr;
    gap: 16px;
  }}
  .todays-headlines .headline-item {{
    border-right: none;
    padding-right: 0;
    padding-bottom: 16px;
    border-bottom: 1px dotted #ddd;
  }}
  .todays-headlines .headline-item:last-child {{
    border-bottom: none;
    padding-bottom: 0;
  }}
}}
.todays-headlines .headline-title {{
  display: block;
  font-family: 'Noto Serif JP', 'Old Standard TT', serif;
  font-weight: 700;
  font-size: 16px;  /* 5/19 神山さん観察「縦割り格上げ」: 14 → 16 */
  line-height: 1.5;
  margin: 0 0 6px;
}}
.todays-headlines .headline-title a {{
  color: inherit;
  text-decoration: none;
  border-bottom: 1px dotted var(--ink-soft);
}}
.todays-headlines .headline-title a:hover {{
  border-bottom-style: solid;
}}
.todays-headlines .headline-summary {{
  font-size: 12px;
  color: #333;
  line-height: 1.7;
  margin: 4px 0;
}}
.todays-headlines .headline-byline {{
  display: block;
  font-size: 11px;
  color: #888;
}}
"""


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


def _render_todays_headlines(headlines: list[dict] | None) -> str:
    """Today's Headlines HTML を生成 (Sprint 7 Phase 2 Step 2, 2026-05-19).

    Page II 下段に挿入する `<aside class="todays-headlines">` セクション。
    headlines が空 or None なら空文字列を返し、Page II の HTML 末尾には何も
    挿入されない（page2 の既存挙動を破壊しない）。

    summary は ``todays_headlines.format_summary`` で 100 字 truncate。
    description 空 (Yahoo! 等の title-only feed) なら summary <p> 自体を省略。
    """
    if not headlines:
        return ""

    items: list[str] = []
    for art in headlines:
        title = art.get("title") or ""
        url = art.get("url") or ""
        source = art.get("source_name") or ""
        # C14 (Sprint 8): main() で LLM 要約を art["summary"] に事前計算済みなら
        # それを使う。未計算（テスト等）なら format_summary に fallback。
        summary = art.get("summary")
        if summary is None:
            summary = todays_headlines.format_summary(art)

        if url:
            title_html = (
                f'<a href="{_esc(url)}" target="_blank" rel="noopener noreferrer">'
                f'{_esc(title)}</a>'
            )
        else:
            title_html = _esc(title)

        summary_html = (
            f'      <p class="headline-summary">{_esc(summary)}</p>\n'
            if summary else ""
        )

        items.append(
            f"""    <li class="headline-item">
      <span class="headline-title">{title_html}</span>
{summary_html}      <span class="headline-byline">{_esc(source)}</span>
    </li>"""
        )
    items_html = "\n".join(items)

    return f"""
<aside class="todays-headlines">
  <h3 class="headlines-banner">Today's Headlines</h3>
  <ol class="headlines-list">
{items_html}
  </ol>
</aside>"""


def build_page_two_v2(
    selections: dict, *, headlines: list[dict] | None = None,
) -> str:
    """Assemble the full Page II <section> block from page2 pipeline selections.

    ``selections`` is the ``Page2Result.selections`` dict mapping
    ``company_key`` (cocolomi / human_energy / web_repo) → ``CompanySelection``.
    Order is fixed (Cocolomi → Human Energy → Web-Repo) per the inaugural
    issue's Page II layout.

    Sprint 7 Phase 2 Step 2 (2026-05-19): optional ``headlines`` 引数を追加。
    None or 空 list なら従来の 3 社朝会のみのレイアウトに戻る（後方互換）。
    与えられた場合は `<aside class="todays-headlines">` を </section> 直前に挿入。
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
    headlines_html = _render_todays_headlines(headlines)
    return f"""<section class="page page-two">
    <div class="page-banner"><span class="pg-num">— Page II —</span> The President's Morning Briefing · Three Companies, One Desk</div>

    <p class="deck" lang="ja" style="text-align:center; margin-bottom:18px;">
      Cocolomi・Human Energy・Web-Repo3社の事業文脈に関わる今朝の話題を、各社につき1本——朝の経営判断のための短い問いを添えて。
    </p>
{rows_html}
{headlines_html}
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
    description = article.get("description") or ""
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

    ``selections`` is the ``Page3Result.selections`` dict mapping region
    keys (R1〜R6) to RegionSelection objects. Order is fixed per
    PAGE3_REGIONS (R1→R6, 1行目左→2行目右).
    """
    items_html: list[str] = []
    for region in PAGE3_REGIONS:
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
.academic-column .item {{
  margin-bottom: 20px;
  padding-bottom: 16px;
  border-bottom: 1px dotted #ccc;
}}
.academic-column .item:last-child {{ border-bottom: none; }}
/* Sprint 8 C41 (2026-05-28): iPad / iPhone レスポンシブ。
   横並び (55%:45%) を縦積み (concept 上、academic 下) に切替。 */
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


def _render_page4_concept_column(concept: dict, essay: str) -> str:
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
      </div>
    </article>""".rstrip()


def _render_page4_academic_item(article: dict) -> str:
    """Render one item in the academic column.

    C36 Step 2b (2026-06-09): 英語ソース多様化に合わせ、title_ja/desc_ja を採用。
    desc_ja は Sprint 5 ポリシーにより原文 passthrough（英語ソースは英語のまま）。
    C80 (2026-06-12, Fable review L3): 英語段落に ``lang="ja"`` が付くと
    typography / 読み上げが崩れるため、title と desc で lang を分離。title は
    翻訳済 (ja)、desc は原文ソースの言語に従う。
    """
    title_ja = article.get("title_ja") or article.get("title") or ""
    desc_ja = article.get("desc_ja") or article.get("description") or ""
    source_name = article.get("source_name") or ""
    url = article.get("url") or ""
    date_label = _format_publish_date_ja(article.get("pub_date"))
    if date_label:
        byline_text = f"出典：{source_name} · {date_label}"
    else:
        byline_text = f"出典：{source_name}"
    title_html = f'<a href="{_esc(url)}" target="_blank" rel="noopener noreferrer">{_esc(title_ja)}</a>' if url else _esc(title_ja)
    # C80: desc の言語属性を Source.language ベースで決定。``_is_japanese_article``
    # は source_language を最優先、fallback で name-heuristic を見る（Sprint 5
    # 設計）。これにより英語ソース desc に ``lang="ja"`` が付く問題を解消。
    desc_is_ja = _is_japanese_article(article)
    desc_lang_attr = "" if desc_is_ja else ' lang="en"'
    return f"""
      <div class="item" lang="ja">
        <h5 class="headline-s">{title_html}</h5>
        <p{desc_lang_attr}>{_esc(desc_ja)}</p>
        <p class="byline" style="font-size: 11px; color: #666; margin-top: 4px;">{_esc(byline_text)}</p>
      </div>""".rstrip()


def _render_page4_academic_column(articles: list[dict]) -> str:
    """Render the right column (3 academic articles)."""
    if not articles:
        items_html = (
            '\n      <div class="item" lang="ja">'
            '\n        <h5 class="headline-s" style="font-style: italic; color: #666;">本日該当なし</h5>'
            '\n      </div>'
        )
    else:
        items_html = "\n".join(_render_page4_academic_item(a) for a in articles)
    return f"""
    <aside class="academic-column" lang="ja">
      <div class="kicker">学術ニュース</div>
{items_html}
    </aside>""".rstrip()


def build_page_four_v2(
    target_date: date,
    *,
    pre_evaluated: dict[str, dict] | None = None,
    displayed_urls_today: set[str] | None = None,
) -> tuple[str, dict]:
    """Build the full <section class="page page-four"> block.

    Returns ``(html, telemetry)`` where telemetry contains:
      - concept: the chosen concept dict
      - essay_result: {essay, is_fallback, cost_usd}
      - articles_result: {articles, from_cache, cost_usd, rotation}

    C49 案A (Sprint 8, 2026-06-01) — ``displayed_urls_today`` を受け取って
    Page IV academic rotator に渡す。同日に他面（特に Page III R6）で採用
    された URL を構造的に除外する。
    """
    # 1) Concept of the week
    concept = page4_concept_selector.select_concept_for_today(today=target_date)
    essay_result = page4_concept_writer.write_essay(concept)

    # 2) Academic 3 articles (rotation)
    articles_result = page4_rotator.get_today_articles(
        target_date,
        pre_evaluated=pre_evaluated,
        displayed_urls_today=displayed_urls_today,
    )

    # C36 Step 2b (2026-06-09): 英語ソース多様化に伴い翻訳経路を追加。
    # title のみ翻訳（Sprint 5 ポリシー）、desc は原文 passthrough。
    translate_for_render(articles_result["articles"])

    # 3) Render
    concept_html = _render_page4_concept_column(concept, essay_result["essay"])
    academic_html = _render_page4_academic_column(articles_result["articles"])

    page = f"""<section class="page page-four">
    <div class="page-banner"><span class="pg-num">— Page IV —</span> Arts &amp; Letters · A Page for Slow Reading</div>

    <div class="page-four-grid">
{concept_html}
{academic_html}
    </div>
  </section>"""

    telemetry = {
        "concept": concept,
        "essay_result": essay_result,
        "articles_result": articles_result,
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

PAGE_FIVE_CSS_MARKER = "/* === Page V (Sprint 4 layout swap, was Sprint 3 Step D) === */"

PAGE_FIVE_CSS = f"""
{PAGE_FIVE_CSS_MARKER}
.page-five-content {{
  display: grid;
  grid-template-rows: 40% 60%;
  padding: 16px 24px;
}}
.serendipity-article {{
  padding-bottom: 24px;
  margin-bottom: 24px;
  border-bottom: 1px solid #ccc;
}}
.serendipity-article .kicker {{
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.1em;
  color: #666;
  text-transform: uppercase;
  margin-bottom: 8px;
}}
.serendipity-article .article-title {{
  font-family: 'Noto Serif JP', 'Old Standard TT', serif;
  font-size: 18px;
  font-weight: 700;
  line-height: 1.5;
  margin: 0 0 10px;
}}
.serendipity-article .description {{
  font-family: 'Noto Serif JP', 'Old Standard TT', serif;
  font-size: 14px;
  line-height: 1.8;
  color: #333;
  margin-bottom: 8px;
}}
.serendipity-article .serendipity-byline {{
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
.serendipity-article,
.ai-kamiyama-column {{
  min-width: 0;
  overflow-wrap: break-word;
  word-break: normal;
}}
.ai-kamiyama-column .column-body p,
.ai-kamiyama-column .column-title,
.ai-kamiyama-column .ai-source-ref,
.ai-kamiyama-column .ai-article-summary,
.serendipity-article .article-title,
.serendipity-article .description {{
  overflow-wrap: break-word;
}}
@media (max-width: 834px) {{
  .page-five-content {{
    grid-template-rows: auto auto;
    padding: 16px 18px;
    row-gap: 12px;
  }}
  .serendipity-article {{
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
  .serendipity-article .article-title {{ font-size: 16px; }}
  .serendipity-article .description {{ font-size: 13px; }}
}}
"""


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
    pre_evaluated: dict[str, dict] | None = None,
    page_two_headlines: list[dict] | None = None,
    page3_result=None,
    page4_telemetry: dict | None = None,
) -> tuple[str, dict]:
    """Build the full <section class="page page-five"> block (Columns & Serendipity).

    Returns (html, telemetry) — telemetry contains:
      - serendipity (article + category + tie_candidates + cost_usd)
      - ai_article (AIかみやま 論評対象記事、Sprint 7 Phase 1 Step 2 追加)
      - column (column_title + column_body + is_fallback + elapsed_ms)

    Sprint 7 Phase 1 Step 2 (2026-05-19):
    - AIかみやま column の対象記事を serendipity から独立化

    C40 第二弾 (Sprint 8, 2026-05-30):
    - AIかみやま 候補プールを「当日確定紙面（Page II Today's Headlines +
      Page III + Page IV 学術記事）」に限定。
    - 旧 page1_result の candidates_scored 全体参照は廃止。Page I 除外は
      候補プールに含めないことで実現（C45 D2 と同じ哲学）。
    - 連続日重複は他面 dedup が連動して自動回避。
    """
    from .page5 import ai_kamiyama_selector as page5_ai_selector

    # 1) Select the serendipity article
    serendipity = page5_serendipity.select_for_today(
        target_date=target_date, pre_evaluated=pre_evaluated,
    )

    # 2) Render placeholder if no candidates
    if serendipity["is_placeholder"]:
        html = _render_page_five_placeholder()
        return html, {
            "serendipity": serendipity,
            "ai_article": None,
            "column": None,
        }

    serendipity_article = serendipity["article"]

    # 3) AIかみやま 専用の記事選定（C40 第二弾 神山案、2026-05-30）。
    # 候補プールは当日確定紙面：Page II Today's Headlines + Page III R1-R6 +
    # Page IV 学術記事。Page I は意図的に除外（C45 D2）、Page V serendipity も
    # 背中合わせ枠なので除外。category フィルタは候補プールが既に編集判断を
    # 通過しているため skip（eligible_categories=None）。
    page3_selections = (
        getattr(page3_result, "selections", None) if page3_result is not None else None
    )
    page4_articles = None
    if page4_telemetry:
        page4_articles = (page4_telemetry.get("articles_result") or {}).get("articles")
    ai_article = page5_ai_selector.select_ai_kamiyama_article(
        target_date=target_date,
        page_two_headlines=page_two_headlines,
        page3_selections=page3_selections,
        page4_articles=page4_articles,
        serendipity_article=serendipity_article,
        registry=None,
        eligible_categories=None,
    )

    # 4) AIかみやま column generation via miibo
    #    ai_article がゼロ件なら fallback column を組み立てる（API は呼ばない）
    if ai_article is not None:
        column = page5_ai_kamiyama.write_column(ai_article)
    else:
        column = {
            "column_title": "本日 AIかみやま休載",
            "column_body": "本日は AIかみやま に渡す独立記事が候補ゼロでした。",
            "is_fallback": True,
            "raw_response": None,
            "elapsed_ms": 0,
            "ai_kamiyama_called": False,
            "ai_kamiyama_failed": False,
            "fallback_used": True,
        }

    # Sprint 5 task #5 (2026-05-04): selector は column 生成前に history へ
    # placeholder 値（false 固定）で書込済。column 生成結果と AIかみやま 記事メタを
    # 反映するため同じ entry を見つけて上書きする。
    page5_serendipity.update_history_column_fields(
        target_date=target_date,
        article_url=(serendipity_article.get("url") or ""),
        ai_kamiyama_called=bool(column.get("ai_kamiyama_called", False)),
        ai_kamiyama_failed=bool(column.get("ai_kamiyama_failed", False)),
        fallback_used=bool(column.get("fallback_used", False)),
        ai_kamiyama_url=(ai_article.get("url") if ai_article else None),
        ai_kamiyama_title=(ai_article.get("title") if ai_article else None),
        ai_kamiyama_category=(ai_article.get("category") if ai_article else None),
        ai_kamiyama_source_name=(ai_article.get("source_name") if ai_article else None),
    )

    # 5) Render full structure
    html = _render_page_five(serendipity, ai_article, column)
    return html, {
        "serendipity": serendipity,
        "ai_article": ai_article,
        "column": column,
    }


def _render_page_five(
    serendipity: dict,
    ai_article: dict | None,
    column: dict,
) -> str:
    """Render Page V: serendipity article (top 40%) + AIかみやま column (bottom 60%).

    Sprint 4 Phase 2: order flipped from Sprint 3 Step D layout (was AI on top).

    Sprint 7 Phase 1 Step 2 (2026-05-19): AIかみやま column の対象記事を
    serendipity から独立化。下部に「対象記事：title (source)」の 1 行を追加して
    読者に「AIかみやま が何を論評しているか」を明示。
    ``ai_article=None`` の場合は対象記事行を省略（AIかみやま 候補ゼロ時の fallback）。
    """
    article = serendipity["article"]
    title = (article.get("title") or "").strip()
    source_name = (article.get("source_name") or "").strip()
    url = (article.get("url") or "").strip()
    # C19 (5/21 神山さん観察): Serendipity の文章が短い。120 字 hardcode
    # truncate を 300 字に拡張し、RSS の content:encoded があれば description
    # の代わりにそちらを使う（_get_serendipity_description_text が吸収）。
    description = _truncate_to_chars(
        page5_serendipity._get_serendipity_description_text(article), 300,
    )
    date_label = _format_publish_date_ja(article.get("pub_date"))
    if date_label:
        article_byline = f"出典：{source_name} · {date_label}"
    else:
        article_byline = f"出典：{source_name}"

    column_title = column.get("column_title", "")
    column_body = column.get("column_body", "")

    # Sprint 6: serendipity の article-title を <a> で囲む。元記事タイトルが
    # 見える場所なので、Q2 設計原則に従いタイトルにリンク。
    title_html = (
        f'<a href="{_esc(url)}" target="_blank" rel="noopener noreferrer">{_esc(title)}</a>'
        if url else _esc(title)
    )

    # AIかみやま 対象記事の参照行（Sprint 7 Phase 1 Step 2）
    ai_source_ref_html = ""
    if ai_article:
        ai_title = (ai_article.get("title") or "").strip()
        ai_source = (ai_article.get("source_name") or "").strip()
        ai_url = (ai_article.get("url") or "").strip()
        if ai_title:
            ai_title_html = (
                f'<a href="{_esc(ai_url)}" target="_blank" rel="noopener noreferrer">{_esc(ai_title)}</a>'
                if ai_url else _esc(ai_title)
            )
            source_suffix = f"（{_esc(ai_source)}）" if ai_source else ""
            ai_source_ref_html = (
                f'<p class="ai-source-ref">対象記事：{ai_title_html}{source_suffix}</p>'
            )

    # AIかみやま 対象記事のサマリ（Sprint 8, 5/20 神山さん観察 C16）。
    # 対象記事は独立選定で他面に乗らないため、概要が無いと読者に
    # 「何への論評か」が伝わらない。description を 200 字で表示。
    ai_article_summary_html = ""
    if ai_article:
        ai_desc = _truncate_to_chars(ai_article.get("description") or "", 200)
        if ai_desc:
            ai_article_summary_html = (
                f'<p class="ai-article-summary">{_esc(ai_desc)}</p>'
            )

    return f"""<section class="page page-five">
    <div class="page-banner"><span class="pg-num">— Page V —</span> Columns &amp; Serendipity · A Room with a Different Window</div>

    <div class="page-five-content" lang="ja">
      <aside class="serendipity-article">
        <div class="kicker">今朝出会った1本</div>
        <h3 class="article-title">{title_html}</h3>
        <p class="description">{_esc(description)}</p>
        <p class="serendipity-byline">{_esc(article_byline)}</p>
      </aside>

      <article class="ai-kamiyama-column">
        <div class="kicker">AIかみやまの一筆</div>
        {ai_source_ref_html}
        {ai_article_summary_html}
        <h3 class="column-title">{_esc(column_title)}</h3>
        <div class="column-body">
          <p>{_esc(column_body)}</p>
        </div>
        <p class="ai-byline">— AIかみやま</p>
      </article>
    </div>
  </section>"""


def _render_page_five_placeholder() -> str:
    """Render the both-sides-empty placeholder (no serendipity candidate)."""
    return """<section class="page page-five">
    <div class="page-banner"><span class="pg-num">— Page V —</span> Columns &amp; Serendipity · A Room with a Different Window</div>

    <div class="page-five-placeholder" lang="ja">
      <p>本日は出会いがありませんでした。</p>
      <p>明日の更新をお待ちください。</p>
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
) -> tuple[str, dict]:
    """Build the full <section class="page page-six"> block (Leisure 4 columns).

    Returns (html, telemetry).
    """
    # 1) Books / Music / Outdoor — recommend + LLM column
    books = page6_leisure.recommend_for_area(
        "books", target_date=target_date, pre_evaluated=pre_evaluated,
    )
    music = page6_leisure.recommend_for_area(
        "music", target_date=target_date, pre_evaluated=pre_evaluated,
    )
    outdoor = page6_leisure.recommend_for_area(
        "outdoor", target_date=target_date, pre_evaluated=pre_evaluated,
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

def _print_dry_run_report(result: PipelineResult, fetched_by_source: dict[str, int]) -> None:
    print()
    print("=== Dry-run report ===")
    print()
    print("Per-source fetch counts:")
    for name, n in fetched_by_source.items():
        print(f"  {name:>16}: {n} articles")
    print(f"  {'TOTAL':>16}: {result.fetched_total}")
    print()
    print(f"Stage 1: {result.stage1_passed} passed, {result.stage1_excluded} excluded")
    print(
        f"Stage 2: {result.stage2_evaluated} evaluated, {result.stage2_errors} errors, "
        f"cost=${result.stage2_cost_usd:.4f}"
    )
    print()
    print("All candidates ranked by final_score:")
    for i, a in enumerate(result.candidates_scored, 1):
        score = a.get("final_score", 0.0)
        src = a.get("source_name", "?")
        # Compact aesthetic breakdown.
        bk = "/".join(
            str(a.get(k, "?")) for k in ("美意識1", "美意識3", "美意識5", "美意識6", "美意識8")
        )
        m2 = a.get("美意識2_machine", "?")
        warn = " [missing_a2]" if a.get("missing_aesthetic_2_warning") else ""
        title = a.get("title", "")[:60]
        print(
            f"  {i:2d}. {score:6.2f}  [1/3/5/6/8={bk}, m2={m2}]{warn}"
            f"  ({src[:20]})  {title}"
        )
    print()
    print(f"Selected for Page I (top {N_TOP} + sec {N_SECONDARIES}):")
    for i, a in enumerate(result.selected, 1):
        role = "TOP" if i == 1 else f"SEC{i-1}"
        score = a.get("final_score", 0.0)
        src = a.get("source_name", "?")
        title = a.get("title", "")[:70]
        print(f"  [{role}] {score:6.2f}  ({src[:20]})  {title}")


def _dry_run_sidebar_preview(top: dict) -> None:
    """Translate top + call generate_why_important + print 3-point preview.

    Exists only for ``--dry-run`` so the operator can sanity-check sidebar
    output without writing HTML. Production rendering goes through
    ``_build_sidebar(top)`` inside ``build_page_one_v2``.
    """
    print()
    print("=== Sidebar preview (Page I top) ===")
    if _is_japanese_source(top.get("source_name", "")):
        top["title_ja"] = top.get("title", "")
        top["desc_ja"] = top.get("description", "")
    else:
        try:
            _translate_article(top)
        except Exception as e:
            print(f"  translation failed: {e}")
            top["title_ja"] = top.get("title", "")
            top["desc_ja"] = top.get("description", "")
    print(f"  top.title_ja: {top.get('title_ja','')[:80]}")
    try:
        points = generate_why_important(top)
        used_fallback = False
    except (
        WhyImportantLLMError,
        WhyImportantValidationError,
        CapExceededError,
    ) as e:
        print(f"  LLM failed → static fallback ({e})")
        points = static_why_important(top)
        used_fallback = True
    print(f"  fallback used: {used_fallback}")
    for k in (
        "point_1_subject",
        "point_2_significance",
        "point_3_executive_perspective",
    ):
        v = points.get(k, "")
        n = len(v)
        in_band = (
            "OK" if 60 <= n <= 100
            else "soft-out" if 50 <= n <= 120
            else "hard-out"
        )
        print(f"  [{k}] {n}字 ({in_band})")
        print(f"    {v}")


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
    page1_result,
    page2_result,
    write_log: bool,
):
    """Page III pipeline: 6領域 × 各1本.

    Stage 2 結果は page1 と共有（page1 で評価済の Foresight / Economist 等
    の URL は再評価しない、page3_design_v1.md §10.4）。
    """
    print(
        "Fetching business + geopolitics + academic + books for Page III...",
        file=sys.stderr,
    )

    # Stage 2 結果共有：page1 で評価済の article dict をキャッシュ。
    pre_evaluated: dict[str, dict] = {}
    for art in page1_result.candidates_scored:
        url = art.get("url")
        if url:
            pre_evaluated[url] = art

    # 当日 page1 + page2 で選定された URL を当日他面 dedup として渡す。
    today_urls: set[str] = set()
    for art in page1_result.selected:
        url = art.get("url")
        if url:
            today_urls.add(url)
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
        pre_evaluated=pre_evaluated,
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
    for region in PAGE3_REGIONS:
        sel = page3_result.selections.get(region)
        display = PAGE3_REGION_DISPLAY_NAMES[region]
        if sel is None or sel.article is None:
            print(f"  [{region} {display:<18}] 本日該当なし  ({sel.fallback_reason if sel else 'no entry'})")
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


def _v3_swap_will_apply(target: date, *, pivotal_path: Path | None = None) -> bool:
    """Return True if regen_front_page_v3 would swap Page I on this date.

    C45 D2 (Sprint 8, 2026-05-29): editorial が紙面に出ない記事を引用する
    事象の真因対策。本番 cron は regen_front_page_v3 経由で呼ばれ、
    monthly_pivotal.json に当該日の週が登録されていれば Page I が essay 形式に
    surgical swap される。swap 後の Page I に v2 の top4 は出てこないため、
    editorial 生成時に Page I を context から除外する必要がある。

    本関数は monthly_pivotal を覗いて swap 適用可否のみ判定する（v3 が呼ばれた
    かどうかは見ない）。v2 を単独で叩く dev 経路では Page I が v2 として残る
    のに editorial から外れる軽い不整合があるが、本番経路 (v3) と整合を優先。

    Pivotal load 失敗時は False（保守側）に倒し、Page I を editorial に含める
    従来挙動を維持する。
    """
    try:
        monthly = load_monthly_pivotal(pivotal_path or DEFAULT_PIVOTAL_PATH)
        return find_week_for_date(target, monthly) is not None
    except Exception as e:  # noqa: BLE001 — どんな失敗でも保守的 fallback
        print(
            f"[editorial] monthly_pivotal load failed "
            f"({type(e).__name__}: {e}), assuming v3 swap NOT applicable",
            file=sys.stderr,
        )
        return False


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
        target = date.today()

    print(f"Target date: {target.isoformat()}", file=sys.stderr)

    # 1) Fetch Page I sources
    print(f"Fetching candidates from {len(SOURCE_NAME_FILTERS)} sources...", file=sys.stderr)
    articles, per_source = fetch_candidates()
    if not articles:
        print("No candidates fetched. Aborting.", file=sys.stderr)
        return 1
    print(f"  fetched {len(articles)} articles total", file=sys.stderr)

    # 2) Pipeline (Stage 1 → 2 → 3) for Page I
    print("Running Page I selection pipeline (Stage 1 → 2 → 3)...", file=sys.stderr)
    result = run_pipeline(articles)
    result.fetched_by_source = per_source

    # 2b) Sprint 2 Step D: Page I dedup against past 7 days' displayed URLs.
    page1_displayed = load_recently_displayed_urls(
        days_back=PAGE1_DEDUP_DAYS, page="page1", until_date=target,
    )
    if page1_displayed:
        before = len(result.candidates_scored)
        deduped_candidates = filter_recently_displayed(
            result.candidates_scored, page1_displayed,
        )
        removed = before - len(deduped_candidates)
        print(
            f"[dedup] Page I: removed {removed}/{before} candidates "
            f"already shown in past {PAGE1_DEDUP_DAYS} days "
            f"({len(deduped_candidates)} remain)",
            file=sys.stderr,
        )
        result.candidates_scored = deduped_candidates
        result.selected = deduped_candidates[: N_TOP + N_SECONDARIES]

    if len(result.selected) < N_TOP + N_SECONDARIES:
        print(
            f"WARNING: Page I 候補枯渇 ({len(result.selected)}/{N_TOP + N_SECONDARIES} 本)",
            file=sys.stderr,
        )
        # If we have ≥1 article we still try to render. If 0, abort.
        if len(result.selected) == 0:
            print("ERROR: 0 candidates after dedup. Aborting.", file=sys.stderr)
            _print_dry_run_report(result, per_source)
            return 1

    # 3) Page II pipeline (independent fetch from companies.md High)
    page2_result = None
    if not args.skip_page2:
        page2_result = _run_page2_selection(
            target, write_log=not args.dry_run, threshold=args.page2_threshold,
        )

    # 3b) Page III pipeline (Sprint 3 Step A): 6領域 × 各1本.
    # Stage 2 結果は page1 と共有（page3_design_v1.md §13 Q6）。
    page3_result = None
    if not args.skip_page3:
        page3_result = _run_page3_selection(
            target,
            page1_result=result,
            page2_result=page2_result,
            write_log=not args.dry_run,
        )

    if args.dry_run:
        _print_dry_run_report(result, per_source)
        if page2_result is not None:
            _print_page2_report(page2_result)
        if page3_result is not None:
            _print_page3_report(page3_result)
        if result.selected:
            _dry_run_sidebar_preview(result.selected[0])
        return 0

    # 4) Translate selected (Page I + Page II articles).
    print("Translating Page I articles...", file=sys.stderr)
    translate_for_render(result.selected)
    if page2_result is not None:
        page2_articles = [
            sel.article for sel in page2_result.selections.values()
            if sel.article is not None
        ]
        if page2_articles:
            print("Translating Page II articles...", file=sys.stderr)
            translate_for_render(page2_articles)

    # 4b) Page IV pipeline (Sprint 3 Step B): concept + 3 academic articles.
    page_four_html: str | None = None
    page_four_telemetry: dict | None = None
    page_five_html: str | None = None
    page_five_telemetry: dict | None = None
    page_six_html: str | None = None
    page_six_telemetry: dict | None = None
    if not args.skip_page4:
        print("Building Page IV (concept + 3 academic articles)...", file=sys.stderr)
        # Reuse Stage 2 cache for academic + books overlap (small but consistent).
        pre_evaluated_for_page4: dict[str, dict] = {
            a["url"]: a for a in result.candidates_scored if a.get("url")
        }
        # C49 案A (Sprint 8, 2026-06-01): Page III (page3_result.selections) で
        # 採用済の URL を Page IV に渡して構造的に除外する。5/15-19 / 5/25 / 5/31
        # で観測された集英社新書プラス記事の 3 面 / 4 面 同時表示（30 日中 7 件=
        # 23%）への対処。C40 案1+案2 / C40 第二弾 / C45 D2 と同じ「当日確定他面
        # 情報を後段 context に入れる」哲学の延長。
        page4_other_pages_urls: set[str] = set()
        if page3_result is not None:
            for sel in page3_result.selections.values():
                art = getattr(sel, "article", None)
                if art and art.get("url"):
                    page4_other_pages_urls.add(art["url"])
        try:
            page_four_html, page_four_telemetry = build_page_four_v2(
                target,
                pre_evaluated=pre_evaluated_for_page4,
                displayed_urls_today=page4_other_pages_urls or None,
            )
            essay_meta = page_four_telemetry["essay_result"]
            articles_meta = page_four_telemetry["articles_result"]
            print(
                f"  Page IV: concept={page_four_telemetry['concept']['id']}, "
                f"essay_fallback={essay_meta['is_fallback']}, "
                f"articles={len(articles_meta['articles'])}/3, "
                f"from_cache={articles_meta['from_cache']}, "
                f"cost=${essay_meta['cost_usd'] + articles_meta['cost_usd']:.4f}",
                file=sys.stderr,
            )
        except Exception as e:
            print(
                f"[page4] FAILED: {type(e).__name__}: {e} — skipping Page IV regen",
                file=sys.stderr,
            )
            page_four_html = None

    # 4b.5) C40 第二弾 (Sprint 8, 2026-05-30): Today's Headlines を Page V より前に
    # 選定する。AIかみやま selector が candidate pool として headlines を参照する
    # ため、Page V build の前に確定させる必要がある。LLM 要約 (generate_summary_with_llm)
    # は表示用なので Page II HTML 構築直前まで遅延する（後段 §5 に残置）。
    headlines: list[dict] = []
    if page2_result is not None:
        recent_headlines_urls = load_recently_displayed_urls(
            todays_headlines.HEADLINES_DEDUP_DAYS,
            page="headlines",
            until_date=target,
        )
        headlines = todays_headlines.select_todays_headlines(
            target_date=target,
            candidates_scored=result.candidates_scored,
            page1_selected=result.selected,
            page3_selections=(
                page3_result.selections if page3_result is not None else None
            ),
            recent_displayed_urls=recent_headlines_urls,
        )
        print(
            f"  Today's Headlines preselected: {len(headlines)} 件 "
            f"({', '.join((h.get('source_name') or '')[:10] for h in headlines) or '(none)'})",
            file=sys.stderr,
        )

    # 4c) Page V pipeline (Sprint 4: Columns & Serendipity, was Sprint 3 Step D)
    if not args.skip_page5:
        print(
            "Building Page V (serendipity + AIかみやま column via miibo)...",
            file=sys.stderr,
        )
        pre_evaluated_for_page5: dict[str, dict] = {
            a["url"]: a for a in result.candidates_scored if a.get("url")
        }
        try:
            page_five_html, page_five_telemetry = build_page_five_v2(
                target,
                pre_evaluated=pre_evaluated_for_page5,
                page_two_headlines=headlines,
                page3_result=page3_result,
                page4_telemetry=page_four_telemetry,
            )
            sty = page_five_telemetry["serendipity"]
            ai_art = page_five_telemetry.get("ai_article")
            col = page_five_telemetry.get("column")
            if sty["is_placeholder"]:
                print(
                    f"  Page V: PLACEHOLDER ({sty['category']}, "
                    f"tied={sty['tie_candidates']}, no candidates)",
                    file=sys.stderr,
                )
            else:
                article = sty["article"]
                col_status = (
                    "fallback" if col["is_fallback"]
                    else f"AIかみやま OK ({col['elapsed_ms']}ms)"
                )
                ai_src = (
                    ai_art.get("source_name", "")[:20] if ai_art else "(no candidate)"
                )
                print(
                    f"  Page V: serendipity={sty['category']} ({article.get('source_name', '')[:20]}), "
                    f"ai_kamiyama={ai_src}, "
                    f"column={col_status}",
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
        pre_evaluated_for_page6: dict[str, dict] = {
            a["url"]: a for a in result.candidates_scored if a.get("url")
        }
        try:
            page_six_html, page_six_telemetry = build_page_six_v2(
                target, pre_evaluated=pre_evaluated_for_page6,
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
        # C45 D2 (Sprint 8, 2026-05-29): v3 swap が適用される日は Page I の
        # v2 top4 が essay に置換されて最終紙面に出ないため、editorial の
        # context から Page I を除外する。これにより editorial が「紙面に存在
        # しない記事」を引用する事象（C45 真因）を防ぐ。v3 swap 不適用日は
        # 従来通り Page I を含める。
        v3_will_apply = _v3_swap_will_apply(target)
        page_one_for_editorial = None if v3_will_apply else result.selected
        if v3_will_apply:
            print(
                "[editorial] C45 D2: v3 swap applicable for this date → "
                "excluding Page I from editorial context",
                file=sys.stderr,
            )
        ctx = editorial_context.build_editorial_context(
            page_one_selected=page_one_for_editorial,
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

    # 5) Render Page I + Page II + Page III
    print("Building Page I HTML...", file=sys.stderr)
    page_one_html = build_page_one_v2(result.selected, target_date=target)
    page_two_html: str | None = None
    if page2_result is not None:
        print("Building Page II HTML...", file=sys.stderr)
        # C40 第二弾 (Sprint 8, 2026-05-30): headlines の SELECTION は §4b.5 で
        # 済ませてある（Page V AIかみやま selector が参照するため事前選定が必要）。
        # ここでは LLM 要約（C14, 5/20 神山さん観察、~200 字に拡張）と Page II
        # HTML 構築のみ行う。BBC 以外 / fetch 失敗 / LLM 失敗時は format_summary に fallback。
        for art in headlines:
            art["summary"] = todays_headlines.generate_summary_with_llm(art)
        print(
            "  Today's Headlines summary 文字数: "
            f"{[len(h.get('summary') or '') for h in headlines]}",
            file=sys.stderr,
        )
        page_two_html = build_page_two_v2(
            page2_result.selections, headlines=headlines,
        )
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
    # Sprint 5: Page I も常に CSS injection（タイトル原文大 + 日本語小書き）。
    dated = inject_page_one_css(dated)
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
    page1_urls_displayed = [a.get("url", "") for a in result.selected if a.get("url")]
    page2_urls_displayed: dict[str, str | None] = {k: None for k in PAGE2_COMPANY_ORDER}
    if page2_result is not None:
        for company_key in PAGE2_COMPANY_ORDER:
            sel = page2_result.selections.get(company_key)
            if sel is not None and sel.article is not None:
                page2_urls_displayed[company_key] = sel.article.get("url")
    page3_urls_displayed: list[str | None] = []
    if page3_result is not None:
        for region in PAGE3_REGIONS:
            sel = page3_result.selections.get(region)
            if sel is not None and sel.article is not None:
                page3_urls_displayed.append(sel.article.get("url"))
            else:
                page3_urls_displayed.append(None)
    page4_urls_displayed: list[str] = []
    if page_four_telemetry is not None:
        for art in page_four_telemetry["articles_result"]["articles"]:
            url = art.get("url")
            if url:
                page4_urls_displayed.append(url)
    page5_url_displayed: str | None = None
    if page_five_telemetry is not None:
        sty5 = page_five_telemetry.get("serendipity") or {}
        art5 = sty5.get("article")
        if art5:
            page5_url_displayed = art5.get("url")
    page6_urls_displayed: dict[str, str | None] = {}
    if page_six_telemetry is not None:
        for area in ("books", "music", "outdoor"):
            r = page_six_telemetry.get(area, {})
            art = r.get("article")
            page6_urls_displayed[area] = art.get("url") if art else None
    # C40 (Sprint 8, 2026-05-28): 第2面 Today's Headlines の URL も dedup 用に記録。
    # BBC 等で同 URL のタイトルだけ更新されるパターンに対応するため、過去日の
    # headlines URL を翌朝以降の selector から見えるようにする。
    headlines_urls_displayed: list[str] = []
    if page_two_html is not None:
        headlines_urls_displayed = [
            (h.get("url") or "") for h in headlines if h.get("url")
        ]
    log_path = write_displayed_urls_log(
        target,
        page1_urls=page1_urls_displayed,
        page2_urls_by_company=page2_urls_displayed,
        page3_urls=page3_urls_displayed if page3_result is not None else None,
        page4_urls=page4_urls_displayed if page_four_telemetry is not None else None,
        page5_url=page5_url_displayed,
        page6_urls=page6_urls_displayed if page_six_telemetry is not None else None,
        headlines_urls=headlines_urls_displayed if page_two_html is not None else None,
    )
    print(f"Wrote {log_path}", file=sys.stderr)

    # 6) Optional index update
    if args.update_index:
        update_index_redirect(target)
    else:
        print("(index.html not touched; pass --update-index to rewrite redirect)", file=sys.stderr)

    print()
    print("=== Page I summary ===")
    for i, a in enumerate(result.selected, 1):
        role = "TOP" if i == 1 else f"SEC{i-1}"
        score = a.get("final_score", 0.0)
        src = a.get("source_name", "?")
        print(f"  [{role}] {score:6.2f}  ({src[:20]})  {a.get('title_ja', '')[:60]}")
    print(f"  cost (Page I Stage 2 LLM): ${result.stage2_cost_usd:.4f}")

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
        for region in PAGE3_REGIONS:
            sel = page3_result.selections.get(region)
            display = PAGE3_REGION_DISPLAY_NAMES[region]
            if sel is None or sel.article is None:
                print(f"  [{region} {display:<18}] 本日該当なし")
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
                "（2 領域以上）— logs/page3_selection_*.json で確認推奨"
            )

    if page_four_telemetry is not None:
        print()
        print("=== Page IV summary ===")
        c = page_four_telemetry["concept"]
        e = page_four_telemetry["essay_result"]
        ar = page_four_telemetry["articles_result"]
        print(f"  Concept of the Week: {c['id']}  ({c['name_ja']} / {c['name_en']})")
        print(f"    domain: {c['domain']}, difficulty: {c['difficulty']}")
        print(f"    essay length: {len(e['essay'])} chars, "
              f"fallback: {e['is_fallback']}, cost: ${e['cost_usd']:.4f}")
        print(f"  Academic articles ({len(ar['articles'])}/3, from_cache={ar['from_cache']}):")
        for i, a in enumerate(ar["articles"], 1):
            score = a.get("final_score", 0.0)
            print(f"    [{i}] score={score:6.2f}  ({a.get('source_name', '')[:25]})")
            print(f"        title: {a.get('title', '')[:70]}")
        print(f"  cost (Page IV Stage 2 + concept LLM): "
              f"${e['cost_usd'] + ar['cost_usd']:.4f}")

    if page_five_telemetry is not None:
        print()
        print("=== Page V summary ===")
        sty5 = page_five_telemetry["serendipity"]
        col5 = page_five_telemetry.get("column")
        print(f"  category   : {sty5['category']}  "
              f"(tied: {sty5['tie_candidates']})")
        if sty5["is_placeholder"]:
            print("  PLACEHOLDER (no candidates)")
        else:
            art = sty5["article"]
            print(f"  article    : {art.get('source_name', '')[:30]}")
            print(f"  title      : {art.get('title', '')[:70]}")
            print(f"  pool size  : {sty5['selected_from_pool_size']}")
            if col5 is not None:
                tag = "(fallback)" if col5["is_fallback"] else f"({col5['elapsed_ms']}ms)"
                print(f"  column     : {col5['column_title']} {tag}")
                print(f"  body[:60]  : {col5['column_body'][:60]}")
        print(f"  cost (page5 stage2 LLM): ${sty5.get('cost_usd', 0.0):.4f}")
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
