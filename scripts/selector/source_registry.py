"""Build a mainstream-tag lookup index from sources/*.md.

Articles fetched by ``scripts.lib.drivers.rss`` carry a ``source_name``
that matches the ``Source.name`` parsed from the markdown source files.
This module builds two lookups:

* ``by_name``: ``source_name`` → "true" / "false" / None (unknown)
* ``by_host``: hostname-without-leading-www → same value

The name-based lookup is primary because the RSS driver guarantees it.
The host-based lookup is a fallback for cases where an article is supplied
without a known source_name (e.g. manual paste, future scrapers).

Score mapping per aesthetics_design_v1.md §3.2 美意識2:

* mainstream=false  → 5 (主流外、目利き加点の最大)
* mainstream未設定  → 3 (デフォルト)
* mainstream=true   → 0
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

from ..lib.source import Source, load_all_sources


@dataclass
class SourceRegistry:
    by_name: dict[str, str | None] = field(default_factory=dict)
    by_host: dict[str, str | None] = field(default_factory=dict)
    sources_by_name: dict[str, Source] = field(default_factory=dict)

    def lookup(
        self, source_name: str | None, article_url: str | None = None
    ) -> str | None:
        """Return 'true' / 'false' / None. Prefer source_name; fall back to host."""
        if source_name:
            v = self.by_name.get(source_name)
            if v is not None:
                return v
            # Even if name is in by_name with value None, fall through to host.
        if article_url:
            host = _hostname(article_url)
            if host:
                if host in self.by_host:
                    return self.by_host[host]
                stripped = host.removeprefix("www.")
                if stripped in self.by_host:
                    return self.by_host[stripped]
        return None

    def score(
        self, source_name: str | None, article_url: str | None = None
    ) -> int:
        v = self.lookup(source_name, article_url)
        if v == "false":
            return 5
        if v == "true":
            return 0
        return 3


def _hostname(url: str | None) -> str | None:
    if not url:
        return None
    try:
        return urlparse(url).hostname
    except (ValueError, AttributeError):
        return None


def _normalize_mainstream(raw: str | None) -> str | None:
    if not raw:
        return None
    v = raw.strip().lower()
    if v in ("true", "false"):
        return v
    return None


def build_registry(sources_dir: Path) -> SourceRegistry:
    """Parse sources/*.md and return a SourceRegistry."""
    reg = SourceRegistry()
    for src in load_all_sources(sources_dir):
        v = _normalize_mainstream(src.raw_fields.get("mainstream"))
        reg.by_name[src.name] = v
        reg.sources_by_name[src.name] = src
        host = _hostname(src.url)
        if host:
            host = host.removeprefix("www.")
            existing = reg.by_host.get(host, "__UNSET__")
            # When two sources share a host (rare: PR TIMES tag pages,
            # multiple meti.go.jp endpoints), prefer the false value so the
            # main-stream signal is conservative — `迷ったら non-mainstream に
            # 倒す` per docs/mainstream_criteria_v1.md §運用ルール.
            if existing == "__UNSET__":
                reg.by_host[host] = v
            elif existing == "true" and v == "false":
                reg.by_host[host] = v
    return reg
