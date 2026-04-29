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
from datetime import date, datetime
from pathlib import Path
from typing import Iterable

from .fetch import run as fetch_run
from .lib.source import Article
from .render import replace_page_one
from .selector.stage1 import run_stage1
from .selector.stage2 import run_stage2
from .selector.stage3 import integrate_scores
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
)

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
    if not source_name:
        return False
    return any(pat in source_name for pat in JAPANESE_SOURCE_PATTERNS)


def _kicker_for(source_name: str | None, *, is_top: bool) -> str:
    if not source_name:
        return DEFAULT_KICKER
    for prefix, kicker in KICKER_PREFIXES:
        if prefix in source_name:
            return f"{kicker}・トップ" if is_top else kicker
    return DEFAULT_KICKER


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
    """The 'なぜ重要か' sidebar — generalized to be source-agnostic."""
    title_ja = _esc(top.get("title_ja", ""))
    return f"""
      <aside class="lead-sidebar" lang="ja">
        <div class="kicker">なぜ重要か</div>
        <h4 class="headline-m">本日のトップから読み取るべきこと</h4>
        <p>本紙が今朝、神山さんの美意識基準に従って3ソース（BBC ビジネス、The Economist、Foresight）から選定したトップ記事を、本日の最初に頭に置くべき話題として第1面に据えた。読み解きのための3点：</p>
        <hr class="dotted" />
        <p><strong>1・</strong>記事の主題（『{title_ja}』）が、グローバルな政治・経済の地形にどんな波紋を投げているかを把握する。</p>
        <p><strong>2・</strong>同じ事象を別の視点で扱う他ソース（FT・日経・Bloomberg 等）と読み比べ、フレーミングの違いを観察する。</p>
        <p><strong>3・</strong>このニュースが、今後1週間の意思決定タイムラインに何を加えるかを問う——それが本紙が翌朝以降に追跡すべき焦点となる。</p>
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


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="regen_front_page_v2",
        description="Phase 2 美意識 selection pipeline → archive/<date>.html",
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

    # 1) Fetch
    print(f"Fetching candidates from {len(SOURCE_NAME_FILTERS)} sources...", file=sys.stderr)
    articles, per_source = fetch_candidates()
    if not articles:
        print("No candidates fetched. Aborting.", file=sys.stderr)
        return 1
    print(f"  fetched {len(articles)} articles total", file=sys.stderr)

    # 2) Pipeline (Stage 1 → 2 → 3)
    print("Running selection pipeline (Stage 1 → 2 → 3)...", file=sys.stderr)
    result = run_pipeline(articles)
    result.fetched_by_source = per_source

    if len(result.selected) < N_TOP + N_SECONDARIES:
        print(
            f"ERROR: pipeline returned {len(result.selected)} candidates, "
            f"need {N_TOP + N_SECONDARIES}. Aborting.",
            file=sys.stderr,
        )
        # Still print whatever ranking we have so the user can see what happened.
        _print_dry_run_report(result, per_source)
        return 1

    if args.dry_run:
        _print_dry_run_report(result, per_source)
        return 0

    # 3) Translate selected
    print("Translating selected articles...", file=sys.stderr)
    translate_for_render(result.selected)

    # 4) Render Page I
    print("Building Page I HTML...", file=sys.stderr)
    page_html = build_page_one_v2(result.selected)

    # 5) Load template, update dates, swap Page I, write
    print(f"Loading template: {TEMPLATE_PATH}", file=sys.stderr)
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    dated = update_template_date_strings(template, target)
    final_html = replace_page_one(dated, page_html)

    out_path = _archive_path(target)
    if out_path.exists():
        print(f"Overwriting existing {out_path}", file=sys.stderr)
    out_path.write_text(final_html, encoding="utf-8")
    print(f"Wrote {out_path}", file=sys.stderr)

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
    print(f"  cost (Stage 2 LLM): ${result.stage2_cost_usd:.4f}")
    print(f"  output: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
