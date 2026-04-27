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
