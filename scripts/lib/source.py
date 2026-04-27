"""Source / Article dataclasses + sources/*.md parser.

The Markdown format we parse follows two patterns that emerged across the
sources/ files:

  Pattern A (single-tier, used by business/geopolitics/books/music/outdoor/
  cooking/academic):

      ## High Priority (...)
      ### 1. Source Name ✅
      - **URL**: https://...
      - **RSS**: https://... (or "未提供" / "未検証完了")
      - **形式**: RSS 2.0 / Atom / etc.
      - **対象**: ...
      - **位置付け**: ...

  Pattern B (two-tier, used only by companies.md):

      ## Cocolomi (...)
      ### High Priority (...)
      #### 1. Source Name ✅
      - **URL**: ...
      ...

The parser walks all H3 and H4 headings, treats those whose body opens with
a ``- **URL**:`` bullet as Source records, and infers priority from the most
recent H2 (Pattern A) or H3 (Pattern B) heading above. Category for Pattern B
is the most recent H2.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path


class Status(str, Enum):
    VERIFIED = "verified"   # ✅ feed/URL fetched cleanly during research
    PARTIAL = "partial"     # ⚠️ reachable but RSS missing / scraping needed
    FAILED = "failed"       # ❌ blocked / unreachable / unrecoverable


class Priority(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    REFERENCE = "reference"


class FetchMethod(str, Enum):
    RSS = "rss"
    HTML = "html"
    API = "api"
    YOUTUBE = "youtube"
    BLOCKED = "blocked"     # documented for completeness; no driver dispatches


# Map status emoji to enum.
STATUS_FROM_EMOJI = {
    "✅": Status.VERIFIED,
    "⚠️": Status.PARTIAL,
    "⚠": Status.PARTIAL,
    "❌": Status.FAILED,
    "🔗": Status.VERIFIED,   # cross-ref entries inherit the source's actual status
}

# Substrings that flag a priority section heading. Order matters: longer /
# more specific substrings should appear before shorter ones to avoid
# accidentally matching "毎日" when "毎日〜週数回" is meant. Comparison is done
# case-insensitively against the heading text.
PRIORITY_HEADINGS = [
    ("high priority", Priority.HIGH),
    ("medium priority", Priority.MEDIUM),
    ("reference", Priority.REFERENCE),
    ("毎日チェック", Priority.HIGH),
    ("候補が薄い", Priority.MEDIUM),
    ("月1の俯瞰", Priority.REFERENCE),
    ("(high)", Priority.HIGH),
    ("(medium)", Priority.MEDIUM),
    ("(reference)", Priority.REFERENCE),
    ("（high）", Priority.HIGH),
    ("（medium）", Priority.MEDIUM),
    ("（reference）", Priority.REFERENCE),
    ("毎週", Priority.MEDIUM),
    ("毎日", Priority.HIGH),
    ("月1", Priority.REFERENCE),
]


@dataclass
class Source:
    """One row in a sources/*.md file."""

    name: str
    url: str
    category: str            # "business" / "geopolitics" / "companies:Cocolomi" / etc.
    priority: Priority
    status: Status
    fetch_method: FetchMethod
    rss_url: str | None = None
    site_file: str = ""      # e.g. "business.md"
    description: str = ""    # body text (対象 / 位置付け), kept for prompt context
    raw_fields: dict[str, str] = field(default_factory=dict)

    @property
    def is_actionable(self) -> bool:
        """True if a driver can actually fetch from this source."""
        return self.fetch_method != FetchMethod.BLOCKED


@dataclass
class Article:
    """A normalized article record produced by a SourceDriver."""

    source_name: str
    title: str
    link: str
    description: str = ""
    pub_date: datetime | None = None
    body_paragraphs: list[str] = field(default_factory=list)
    raw: dict = field(default_factory=dict)

    @property
    def fingerprint(self) -> str:
        """The dedupe key. Link is canonical when present, falling back to title."""
        return self.link.strip() or self.title.strip()


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

_HEADING_RE = re.compile(r"^(#{2,4})\s+(.+?)\s*$")
_NUMBERED_PREFIX_RE = re.compile(r"^(\d+)\.\s+(.+?)\s*$")
# Status emoji can include variation selector (️) appended to ⚠. Match
# the trailing emoji explicitly rather than via a character class so the
# composite sequence ⚠+️ is kept together.
_STATUS_EMOJI_RE = re.compile(r"\s+(✅|⚠️|⚠|❌|🔗)\s*$")
_FIELD_RE = re.compile(r"^-\s+\*\*([^*]+)\*\*\s*[:：]\s*(.+?)\s*$")
# A URL stops at ASCII whitespace, common ASCII punctuation that can end a
# sentence, full-width brackets/quotes used in Japanese prose, brace-expansion
# placeholders (``{a,b,c}``), and backticks (Markdown inline-code).
_URL_IN_TEXT_RE = re.compile(r"https?://[^\s)>\"（）「」、。{}`]+")


def _heading_to_priority(text: str) -> Priority | None:
    lowered = text.lower()
    for needle, prio in PRIORITY_HEADINGS:
        if needle in lowered:
            return prio
    return None


def _extract_status(name_part: str) -> tuple[str, Status]:
    """Pull a trailing status emoji off the heading name.

    Returns the name with the leading "N. " number-prefix and trailing emoji
    both stripped. If the heading is not a numbered source line, returns the
    raw text and PARTIAL status.
    """
    m = _NUMBERED_PREFIX_RE.match(name_part)
    if not m:
        return name_part, Status.PARTIAL
    name_with_emoji = m.group(2)
    em = _STATUS_EMOJI_RE.search(name_with_emoji)
    if em:
        emoji = em.group(1)
        name = name_with_emoji[: em.start()].rstrip()
        return name, STATUS_FROM_EMOJI.get(emoji, Status.PARTIAL)
    return name_with_emoji.strip(), Status.PARTIAL


def _decide_fetch_method(rss_value: str, status: Status) -> tuple[FetchMethod, str | None]:
    """Decide how to fetch a source from its RSS field text and status."""
    if status == Status.FAILED:
        # Fully blocked sources document an RSS field with "未検証完了" or similar.
        # We surface them as BLOCKED so the orchestrator can show them in reports
        # without dispatching a driver.
        return FetchMethod.BLOCKED, None
    # The "RSS" field often contains both the URL and an explanation. Pull the
    # first http(s) URL out — that's the actionable endpoint.
    urls = _URL_IN_TEXT_RE.findall(rss_value)
    if urls:
        return FetchMethod.RSS, urls[0].rstrip(".,)")
    # No RSS URL: documented as 未提供 / 廃止 / 等. Fall through to HTML scraping
    # (handled per-site by HtmlScrapeDriver subclasses).
    return FetchMethod.HTML, None


def _parse_one_block(
    name_part: str,
    body_lines: list[str],
    category: str,
    priority: Priority,
    site_file: str,
) -> Source | None:
    name, status = _extract_status(name_part)
    fields: dict[str, str] = {}
    rss_extra_urls: list[str] = []
    in_rss_field = False
    for line in body_lines:
        m = _FIELD_RE.match(line)
        if m:
            key = m.group(1).strip()
            fields[key] = m.group(2).strip()
            in_rss_field = key == "RSS"
            continue
        # An indented bullet directly under the RSS field carries an extra
        # feed URL (multi-section sources like The Economist, Brookings).
        if in_rss_field and line.strip().startswith("- ") and "://" in line:
            for url in _URL_IN_TEXT_RE.findall(line):
                rss_extra_urls.append(url.rstrip(".,)"))
            continue
        # Anything else (or a non-bullet line) ends the RSS field continuation.
        if line.strip() and not line.startswith("  "):
            in_rss_field = False
    url_field = fields.get("URL", "")
    if not url_field:
        return None  # not a source block (e.g. an unrelated heading)
    rss_field = fields.get("RSS", "")
    fetch_method, rss_url = _decide_fetch_method(rss_field, status)
    # If the RSS field itself had no URL but an indented bullet did, use that
    # first sub-URL as the primary endpoint and remember the rest.
    if not rss_url and rss_extra_urls and status != Status.FAILED:
        rss_url = rss_extra_urls[0]
        fetch_method = FetchMethod.RSS
    # If RSS field had no URL but URL field does and status is verified, treat
    # the URL field itself as the candidate (rare, but possible for sites that
    # bake the feed into the public URL).
    main_urls = _URL_IN_TEXT_RE.findall(url_field)
    main_url = main_urls[0].rstrip(".,)") if main_urls else url_field
    pos = fields.get("位置付け", "")
    target = fields.get("対象", "")
    desc = " ".join(part for part in (target, pos) if part)
    if rss_extra_urls:
        # Preserve the full sub-feed list so a future enhancement can iterate
        # them all (e.g. The Economist's 5 sections, Brookings' 3 topics).
        fields["RSS_extra"] = " ".join(rss_extra_urls)
    return Source(
        name=name,
        url=main_url,
        category=category,
        priority=priority,
        status=status,
        fetch_method=fetch_method,
        rss_url=rss_url,
        site_file=site_file,
        description=desc,
        raw_fields=fields,
    )


def parse_sources_md(path: Path) -> list[Source]:
    """Parse one sources/*.md file into Source records."""
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    base_category = path.stem  # e.g. "business"
    sub_category: str | None = None       # set by H2 in companies.md only
    priority: Priority = Priority.MEDIUM  # default until first priority H2/H3
    sources: list[Source] = []
    i = 0
    while i < len(lines):
        m = _HEADING_RE.match(lines[i])
        if not m:
            i += 1
            continue
        level = len(m.group(1))
        heading = m.group(2).strip()
        # Detect priority headings at H2 or H3.
        prio_here = _heading_to_priority(heading)
        if prio_here:
            priority = prio_here
            i += 1
            continue
        # H2 that is not a priority heading is a sub-category (companies.md
        # pattern: ## Cocolomi / ## Human Energy / ## Web-Repo).
        if level == 2:
            # Strip parenthetical like " (生成AI導入支援)" for the key.
            sub = heading.split("（")[0].split("(")[0].strip()
            if sub and sub.lower() not in ("一次情報url", "次回セッションのtodo"):
                sub_category = sub
            i += 1
            continue
        # H3 / H4: candidate source heading. Collect body lines until the next
        # heading.
        body: list[str] = []
        j = i + 1
        while j < len(lines) and not _HEADING_RE.match(lines[j]):
            body.append(lines[j])
            j += 1
        category = (
            f"{base_category}:{sub_category}" if sub_category else base_category
        )
        src = _parse_one_block(heading, body, category, priority, path.name)
        if src:
            sources.append(src)
        i = j
    return sources


def load_all_sources(sources_dir: Path) -> list[Source]:
    """Parse every sources/*.md file in a directory."""
    out: list[Source] = []
    for path in sorted(sources_dir.glob("*.md")):
        out.extend(parse_sources_md(path))
    return out
