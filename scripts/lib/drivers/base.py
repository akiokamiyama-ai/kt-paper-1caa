"""Abstract SourceDriver.

A driver translates a :class:`Source` into a stream of :class:`Article`
records. Subclasses override :meth:`fetch`. Site-specific overrides (custom
User-Agent, alternate RSS path) are applied through :class:`SiteConfig` so
that a driver can stay agnostic to which site it's talking to.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Iterable
from urllib.parse import urlsplit

from ..source import Article, Source

DEFAULT_USER_AGENT = "kt-tribune/0.6 (+local)"
DEFAULT_TIMEOUT = 15

# Allowed URL schemes for any urlopen() in the fetch layer. urllib accepts
# file:// by default, which would let a malicious feed exfiltrate local
# files into the public archive (see docs/security_review_v1.md §3).
ALLOWED_URL_SCHEMES = ("http://", "https://")


def check_url_scheme(url: str) -> None:
    """Reject non-HTTP(S) URLs before urlopen().

    Raises ValueError if the URL does not start with http:// or https://.
    Apply at every fetch boundary that takes a URL from a feed item.
    """
    if not isinstance(url, str) or not url.startswith(ALLOWED_URL_SCHEMES):
        raise ValueError(f"Refused non-HTTP(S) URL: {url!r:.80}")


@dataclass
class SiteConfig:
    """Per-host overrides for fetch behavior.

    Loaded from ``config/site_overrides.toml``. Drivers consult this object
    by hostname when building HTTP requests.
    """

    overrides: dict[str, dict] = field(default_factory=dict)

    def for_url(self, url: str) -> dict:
        host = urlsplit(url).netloc
        return self.overrides.get(host, {})

    def user_agent_for(self, url: str) -> str:
        return self.for_url(url).get("user_agent", DEFAULT_USER_AGENT)

    def note_for(self, url: str) -> str | None:
        return self.for_url(url).get("note")


class SourceDriver(ABC):
    """Abstract base for all source drivers."""

    def __init__(self, site_config: SiteConfig | None = None) -> None:
        self.site_config = site_config or SiteConfig()

    @abstractmethod
    def fetch(self, source: Source) -> Iterable[Article]:
        """Yield Article records for one Source."""
