"""Unified RSS / Atom / RDF driver.

Recognizes three feed dialects discovered during sources/ research:

* RSS 2.0 — ``<rss><channel><item>`` with ``<title>``, ``<link>`` (text),
  ``<description>``, ``<pubDate>``.
* RSS 1.0 (RDF) — ``<rdf:RDF><item>`` with the same children but using the
  Dublin Core ``<dc:date>`` for timestamps. Used by the Nikkei wor.jp mirror,
  ZDNet Japan, 中小企業庁, リセマム.
* Atom 1.0 — ``<feed><entry>`` with ``<title>``, ``<link href="">``,
  ``<summary>`` or ``<content>``, ``<updated>`` / ``<published>``. Used by
  日経サイエンス, 本の雑誌オンライン, 経産省, GraSPP, 音楽ナタリー.

The driver parses all three by walking the XML tree namespace-blind: we
strip namespace prefixes from element tags, then dispatch on the local name.
This avoids depending on a per-feed namespace map.
"""

from __future__ import annotations

import sys
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import Iterable

from ..source import Article, Source
from .base import DEFAULT_TIMEOUT, SourceDriver, check_url_scheme


def _local(tag: str) -> str:
    """Strip the namespace prefix from an XML element tag."""
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


# XML 1.0 disallows control characters U+0000-U+0008, U+000B, U+000C, and
# U+000E-U+001F (only TAB / LF / CR are permitted in this range). Some CMS
# feeds (encountered: bc01.net WordPress export) leak literal U+0007 BEL
# bytes into article HTML. Strip these defensively before XML parsing — for
# well-formed feeds this is a no-op.
_INVALID_XML_BYTES = bytes(
    [c for c in range(0x20) if c not in (0x09, 0x0A, 0x0D)]
)
_INVALID_XML_TRANSLATE = bytes.maketrans(_INVALID_XML_BYTES, b" " * len(_INVALID_XML_BYTES))


def _sanitize_for_xml(data: bytes) -> bytes:
    """Replace XML 1.0 invalid control characters with spaces. No-op on clean feeds."""
    return data.translate(_INVALID_XML_TRANSLATE)


def _text_of(elem: ET.Element | None) -> str:
    if elem is None or elem.text is None:
        return ""
    return elem.text.strip()


def _find_local(parent: ET.Element, names: tuple[str, ...]) -> ET.Element | None:
    """Return the first child whose local name is in ``names``."""
    for child in parent:
        if _local(child.tag) in names:
            return child
    return None


def _parse_date(text: str) -> datetime | None:
    if not text:
        return None
    text = text.strip()
    # Try RFC-822 first (RSS 2.0 pubDate format).
    try:
        return parsedate_to_datetime(text)
    except (TypeError, ValueError):
        pass
    # Fall back to ISO-8601 (Atom updated, dc:date).
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def _extract_link(item: ET.Element) -> str:
    """Pull a link URL from an item, handling RSS text vs Atom href."""
    link_el = _find_local(item, ("link",))
    if link_el is None:
        return ""
    # Atom: <link href="..."/>
    href = link_el.get("href")
    if href:
        return href.strip()
    # RSS: <link>https://...</link>
    return _text_of(link_el)


class RssDriver(SourceDriver):
    """Fetch and parse a syndication feed regardless of dialect."""

    def fetch(self, source: Source) -> Iterable[Article]:
        if not source.rss_url:
            return []
        url = source.rss_url
        try:
            check_url_scheme(url)
        except ValueError as e:
            print(f"  [rss] REJECT {source.name}: {e}", file=sys.stderr)
            return []
        ua = self.site_config.user_agent_for(url)
        req = urllib.request.Request(url, headers={"User-Agent": ua})
        try:
            with urllib.request.urlopen(req, timeout=DEFAULT_TIMEOUT) as resp:
                xml_bytes = resp.read()
        except (urllib.error.URLError, TimeoutError) as e:
            print(f"  [rss] FAIL {source.name}: {e}", file=sys.stderr)
            return []
        try:
            root = ET.fromstring(_sanitize_for_xml(xml_bytes))
        except ET.ParseError as e:
            print(f"  [rss] PARSE {source.name}: {e}", file=sys.stderr)
            return []
        return list(self._iter_items(root, source))

    @staticmethod
    def _iter_items(root: ET.Element, source: Source) -> Iterable[Article]:
        # Walk the tree generically: any descendant whose local name is "item"
        # (RSS / RDF) or "entry" (Atom) is an article candidate.
        for elem in root.iter():
            name = _local(elem.tag)
            if name not in ("item", "entry"):
                continue
            title = _text_of(_find_local(elem, ("title",)))
            link = _extract_link(elem)
            desc = _text_of(_find_local(elem, ("description", "summary", "content")))
            date_text = _text_of(
                _find_local(elem, ("pubDate", "published", "updated", "date"))
            )
            yield Article(
                source_name=source.name,
                title=title,
                link=link,
                description=desc,
                pub_date=_parse_date(date_text),
            )
