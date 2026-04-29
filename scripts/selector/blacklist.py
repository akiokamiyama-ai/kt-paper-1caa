"""Parse docs/blacklist_v1.md and score articles against it.

Only the body of the ``## カテゴリ別キーワード`` section is parsed; all
other sections (用途, ペナルティルール, 運用メモ, バージョン) are
prose and contain no usable keywords.

Within that section, the file is hand-edited and tolerates several
quirks:

* ASCII ``-`` and full-width ``‐`` bullet markers (typo from the kana IME).
* Bullet lines may carry a "category：「kw」「kw」" structure — only the
  bracketed spans are real keywords.
* Lines that lost their bullet but kept their brackets (e.g.
  ``覚醒系：「気づいた瞬間」「人生が変わった」「目が覚めた」``) — same
  rule, extract from brackets.
* ``○``, ``●``, ``〇`` (and runs of them like ``○○``) act as wildcards
  meaning "any short span".
* Sub-headings like ``### 成功談・カリスマ礼賛系（叩き台）`` and the
  horizontal-rule line ``---`` should not become patterns.

Penalty rules (aesthetics_design_v1.md §3.2 美意識4):

* 1 hit  → -3
* 2+ hit → -5
* Cumulative penalty < -10 → exclude (kept for future expansion; the
  blacklist alone cannot trip this in Sprint 1)
"""

from __future__ import annotations

import re
from pathlib import Path

_BRACKETED_RE = re.compile(r"[「『]([^」』]+)[」』]")
_PLACEHOLDER_RUN_RE = re.compile(r"[○●〇]+")
_KEYWORDS_SECTION_HEADING = "カテゴリ別キーワード"


def _to_pattern(keyword: str) -> re.Pattern[str]:
    """Compile a keyword into a regex.

    Runs of ``○`` ``●`` ``〇`` collapse to a single ``.{1,8}`` wildcard so
    that ``○億円調達`` matches ``120億円調達`` and ``驚異の○○`` matches
    ``驚異の事象``.
    """
    sentinel = "\x00WILD\x00"
    masked = _PLACEHOLDER_RUN_RE.sub(sentinel, keyword)
    escaped = re.escape(masked)
    return re.compile(
        escaped.replace(re.escape(sentinel), r".{1,8}"), re.IGNORECASE
    )


def _strip_bullet(line: str) -> tuple[str, bool]:
    """Return (line_without_bullet, had_bullet)."""
    if line.startswith(("- ", "‐ ", "* ")):
        return line[2:].lstrip(), True
    if line[:1] in ("-", "‐", "*"):
        return line[1:].lstrip(), True
    return line, False


def _extract_from_line(line: str, had_bullet: bool) -> list[str]:
    """Pull keyword strings from one bullet-stripped line within the keywords section."""
    bracketed = _BRACKETED_RE.findall(line)
    if bracketed:
        return [b.strip() for b in bracketed if b.strip() and len(b.strip()) >= 2]
    if not had_bullet:
        # Sub-headings, prose, blank lines after losing their bullet have no
        # brackets — drop them.
        return []
    # Bullet line without brackets: drop a "category：" prefix if present, then
    # treat the remainder as the keyword.
    for sep in ("：", ":"):
        if sep in line:
            line = line.split(sep, 1)[1].strip()
            break
    if not line or len(line) < 2:
        return []
    # Drop category-only lines like "成功談・カリスマ礼賛系" or "（叩き台）" markers.
    if line.endswith(("系", "（叩き台）", "(叩き台)")):
        return []
    return [line]


def load_blacklist(path: Path) -> list[re.Pattern[str]]:
    """Read blacklist_v1.md and return a deduplicated list of compiled patterns."""
    text = path.read_text(encoding="utf-8")
    in_keywords_section = False
    seen: set[str] = set()
    patterns: list[re.Pattern[str]] = []
    for raw in text.splitlines():
        stripped = raw.strip()
        # H2 heading switches sections.
        if stripped.startswith("## "):
            heading = stripped[3:].strip()
            in_keywords_section = _KEYWORDS_SECTION_HEADING in heading
            continue
        if not in_keywords_section:
            continue
        # Skip H3 sub-headings, horizontal rules, blank lines, code fences.
        if not stripped or stripped.startswith(("#", "---", "```", "|", ">")):
            continue
        line, had_bullet = _strip_bullet(stripped)
        for kw in _extract_from_line(line, had_bullet):
            if kw in seen:
                continue
            seen.add(kw)
            patterns.append(_to_pattern(kw))
    return patterns


def score_blacklist(
    text: str, patterns: list[re.Pattern[str]]
) -> tuple[int, list[str]]:
    """Count matches and return (penalty, matched_substrings).

    penalty: 0 (no hits) / -3 (1 hit) / -5 (2+ hits).
    """
    if not text or not patterns:
        return 0, []
    hits: list[str] = []
    for p in patterns:
        m = p.search(text)
        if m:
            hits.append(m.group(0))
    if not hits:
        return 0, []
    if len(hits) == 1:
        return -3, hits
    return -5, hits
