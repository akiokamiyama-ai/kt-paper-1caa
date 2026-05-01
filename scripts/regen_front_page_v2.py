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
    run_page2_pipeline,
)
from .selector.why_important import (
    LLMError as WhyImportantLLMError,
    ValidationError as WhyImportantValidationError,
    generate_why_important,
    static_why_important,
)
from .lib.llm import CapExceededError
from .translate import translate

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ARCHIVE_DIR = PROJECT_ROOT / "archive"
TEMPLATE_PATH = ARCHIVE_DIR / "2026-04-25.html"
INDEX_HTML = PROJECT_ROOT / "index.html"

# Source name substrings to fetch from. Matched against `Source.name` in
# scripts.fetch.run() (case-insensitive substring).
SOURCE_NAME_FILTERS: tuple[str, ...] = (
    "BBC Business",
    "The Economist",
    "Foresight",
)

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
    # Strip parenthetical metadata like "BBC Business（本紙第1面で稼働中）" or
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
    """Convert a fetched Article into the dict shape Stage 1+2+rendering expect."""
    desc_clean = _strip_html(article.description)
    body_clean = _strip_html(
        "\n".join(article.body_paragraphs) if article.body_paragraphs else ""
    )
    return {
        "url": article.link,
        "title": article.title,
        "description": desc_clean,
        "body": body_clean,
        "source_name": article.source_name,
        "source_url": None,
        "pub_date": article.pub_date.isoformat() if article.pub_date else None,
    }


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

def _translate_article(article: dict) -> None:
    """Populate ``title_ja`` / ``desc_ja`` in-place. JA sources pass through."""
    source_name = article.get("source_name", "")
    if _is_japanese_source(source_name):
        article["title_ja"] = article.get("title", "")
        article["desc_ja"] = article.get("description", "")
        return
    title = article.get("title", "") or ""
    desc = article.get("description", "") or ""
    title_ja = translate(title) if title else ""
    time.sleep(TRANSLATE_DELAY)
    desc_ja = translate(desc) if desc else ""
    time.sleep(TRANSLATE_DELAY)
    article["title_ja"] = title_ja or title
    article["desc_ja"] = desc_ja or desc


def translate_for_render(articles: list[dict]) -> None:
    """Add title_ja and desc_ja to each article in the selected list."""
    for i, a in enumerate(articles):
        is_ja = _is_japanese_source(a.get("source_name", ""))
        marker = " (JA passthrough)" if is_ja else ""
        print(
            f"  [{i+1}] translating: {a.get('title', '')[:60]}{marker}",
            file=sys.stderr,
        )
        _translate_article(a)


# ---------------------------------------------------------------------------
# Rendering — source-aware Page I builder
# ---------------------------------------------------------------------------

def _esc(s: str) -> str:
    return html.escape(s or "")


def _render_top_body(top: dict) -> str:
    """Single-paragraph dropcap from desc_ja + a byline."""
    desc_ja = top.get("desc_ja", "") or top.get("description", "")
    paragraphs = [f'<p class="dropcap">{_esc(desc_ja)}</p>']
    source_name = top.get("source_name", "") or "外部ソース"
    label = source_name
    for prefix, kicker in KICKER_PREFIXES:
        if prefix in source_name:
            label = kicker.split("・")[0]
            break
    paragraphs.append(
        f'<p class="byline" style="margin-top:8px;">原題：'
        f'<em>{_esc(top.get("title", ""))}</em>　全文：'
        f'<a href="{_esc(top.get("url", ""))}" target="_blank" '
        f'rel="noopener noreferrer">{_esc(label)}</a></p>'
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
        f'        <p class="byline" style="margin-top:6px;">原題：'
        f'<em>{_esc(sec.get("title", ""))}</em>　全文：'
        f'<a href="{_esc(sec.get("url", ""))}" target="_blank" '
        f'rel="noopener noreferrer">{_esc(label)}</a></p>'
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


def build_page_one_v2(articles: list[dict]) -> str:
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
        secondaries_html.append(
            f"""
      <div class="col" lang="ja">
        <div class="kicker">{_esc(kicker)}</div>
        <h3 class="headline-l">{_esc(s.get("title_ja", ""))}</h3>
        <p class="byline">{_esc(byline)}</p>
{_render_secondary_body(s)}
      </div>""".rstrip()
        )

    top_kicker = _kicker_for(top.get("source_name"), is_top=True)
    top_byline = _byline_for(top.get("source_name"))
    top_date_label = _format_publish_date_ja(top.get("pub_date"))
    if top_date_label:
        top_byline = f"{top_byline} · {top_date_label}"

    page = f"""<section class="page page-one">
    <div class="page-banner"><span class="pg-num">— Page I —</span> The Front Page · World &amp; Business</div>

    <article class="front-top">
      <div class="lead-story" lang="ja">
        <div class="kicker">{_esc(top_kicker)}</div>
        <h2 class="headline-xl">{_esc(top.get("title_ja", ""))}</h2>
        <p class="deck">{_esc(top.get("desc_ja", ""))}</p>
        <p class="byline">{_esc(top_byline)}</p>
        <div class="body-3col">
{_render_top_body(top)}
        </div>
      </div>
{_build_sidebar(top)}
    </article>

    <div class="secondaries">{"".join(secondaries_html)}
    </div>
  </section>"""

    return page


# ---------------------------------------------------------------------------
# Rendering — Page II ("社長の朝会")
# ---------------------------------------------------------------------------

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

    # 該当なし: minimal placeholder.
    if sel.article is None or sel.morning_question is None:
        return f"""
    <div class="briefing-row" lang="ja">
      <div class="company">
        {_esc(display_name)}
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
        {_esc(display_name)}
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
# Template date manipulation
# ---------------------------------------------------------------------------

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

    Also injects a 'Test Edition' tag into the colophon footer so the file
    is unambiguously a Sprint 1 preview rather than a published issue.
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
    # Inject "Test Edition" tag right before "For the reader's eyes only"
    # in the colophon. Keep Vol. 1, No. 1 unchanged per Step B sign-off.
    out = out.replace(
        "Vol. 1, No. 1 · For the reader's eyes only",
        "Vol. 1, No. 1 · Test Edition · For the reader's eyes only",
    )
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
    )
    page2_result._exhaustion_initial = page2_exhaustion  # type: ignore[attr-defined]
    return page2_result


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

    if args.dry_run:
        _print_dry_run_report(result, per_source)
        if page2_result is not None:
            _print_page2_report(page2_result)
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

    # 5) Render Page I + Page II
    print("Building Page I HTML...", file=sys.stderr)
    page_one_html = build_page_one_v2(result.selected)
    page_two_html: str | None = None
    if page2_result is not None:
        print("Building Page II HTML...", file=sys.stderr)
        page_two_html = build_page_two_v2(page2_result.selections)

    # 6) Load template, update dates, swap Page I (and II), write
    print(f"Loading template: {TEMPLATE_PATH}", file=sys.stderr)
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    dated = update_template_date_strings(template, target)
    final_html = replace_page_one(dated, page_one_html)
    if page_two_html is not None:
        final_html = replace_page_two(final_html, page_two_html)

    out_path = _archive_path(target)
    if out_path.exists():
        print(f"Overwriting existing {out_path}", file=sys.stderr)
    out_path.write_text(final_html, encoding="utf-8")
    print(f"Wrote {out_path}", file=sys.stderr)

    # 7) Sprint 2 Step D: record displayed URLs for tomorrow's dedup.
    page1_urls_displayed = [a.get("url", "") for a in result.selected if a.get("url")]
    page2_urls_displayed: dict[str, str | None] = {k: None for k in PAGE2_COMPANY_ORDER}
    if page2_result is not None:
        for company_key in PAGE2_COMPANY_ORDER:
            sel = page2_result.selections.get(company_key)
            if sel is not None and sel.article is not None:
                page2_urls_displayed[company_key] = sel.article.get("url")
    log_path = write_displayed_urls_log(
        target,
        page1_urls=page1_urls_displayed,
        page2_urls_by_company=page2_urls_displayed,
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

    print(f"  output: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
