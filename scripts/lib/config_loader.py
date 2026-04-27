"""Load config/site_overrides.toml into a SiteConfig instance."""

from __future__ import annotations

import tomllib
from pathlib import Path

from .drivers.base import SiteConfig

DEFAULT_CONFIG_PATH = (
    Path(__file__).resolve().parent.parent.parent / "config" / "site_overrides.toml"
)


def load_site_config(path: Path | None = None) -> SiteConfig:
    cfg_path = path or DEFAULT_CONFIG_PATH
    if not cfg_path.exists():
        return SiteConfig()
    with open(cfg_path, "rb") as fh:
        raw = tomllib.load(fh)
    sites = raw.get("sites", {})
    return SiteConfig(overrides=sites)
