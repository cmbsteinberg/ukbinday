"""Shared helpers for the LAD lookup tooling."""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlparse

PIPELINE_DIR = Path(__file__).resolve().parent.parent
LAD_OVERRIDES_PATH = PIPELINE_DIR / "lad_overrides.json"


def normalise_domain(url: str) -> str:
    """Extract bare domain from a URL."""
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    domain = urlparse(url).netloc.lower()
    if domain.startswith("www."):
        domain = domain[4:]
    return domain


def _load_overrides() -> dict:
    if not LAD_OVERRIDES_PATH.exists():
        return {}
    return json.loads(LAD_OVERRIDES_PATH.read_text())


def load_unwired_lads() -> dict[str, dict[str, str]]:
    """LAD code -> {blocker, reason} for councils deliberately left without a module.

    lad_lookup.json records the reason as the entry's "status" and the
    blocker (an `api.councils._base.Blocker` value) as its "blocker"; both
    are shown in the deeplink. scripts/lookup/build_lad_lookup refuses a LAD
    that is both listed here and claimed by a module.
    """
    return _load_overrides().get("unwired_lads", {})


def load_deeplink_urls() -> dict[str, str]:
    """LAD code -> council bin page to deeplink to, overriding the composed url.

    Unwired LADs deeplink to their GOV.UK `govuk_url` by default, which is
    sometimes dead (Fylde's `/refuse` 404s after a portal redesign). An entry
    here replaces the entry's "url" at compose time, so api/services/deeplinks
    prefers it over GOV.UK. Only add a code whose default target is wrong.
    """
    return _load_overrides().get("deeplink_urls", {})
