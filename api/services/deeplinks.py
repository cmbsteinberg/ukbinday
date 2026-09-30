"""Deeplink targets for councils with no scraper.

A deeplink is a structured "check on the council website instead" response:
a URL plus a human-readable reason. It covers every unwired LAD in
``lad_lookup.json`` (``scraper_id: null``) — the settled test-fixture
blocklist, the deeplink-unwired settlements (Fylde, Southampton), and the
build backlog (Brighton et al, served deeplink-shaped until ported).

URL priority: council bin page (``url``) > GOV.UK page (``govuk_url``).
Reason: the entry's ``status`` line, or a generic fallback.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

_DATA_DIR = Path(__file__).parent.parent / "data"
_LAD_JSON = _DATA_DIR / "lad_lookup.json"

_GENERIC_REASON = "This council isn't supported for automatic lookups yet."


@dataclass(frozen=True)
class Deeplink:
    lad_code: str
    council_name: str
    url: str
    reason: str


def _lad_entries() -> dict:
    try:
        return json.loads(_LAD_JSON.read_text())
    except (OSError, ValueError):
        return {}


def resolve(lad_code: str) -> Deeplink | None:
    """Return the deeplink for an unwired LAD code, or None if wired/unknown."""
    entry = _lad_entries().get(lad_code)
    if not entry or entry.get("scraper_id"):
        return None
    url = entry.get("url") or entry.get("govuk_url")
    if not url:
        return None
    return Deeplink(
        lad_code=lad_code,
        council_name=entry.get("name", lad_code),
        url=url,
        reason=entry.get("status") or _GENERIC_REASON,
    )


def resolve_by_council_param(param: str) -> Deeplink | None:
    """Match a /lookup ?council= value to an unwired LAD.

    Accepts an LAD code (``E07000119``) or a council name
    (``Fylde``, case-insensitive). Scraper IDs never match — wired
    councils are served by the registry, not here.
    """
    entries = _lad_entries()
    if param in entries:
        return resolve(param)
    lowered = param.lower()
    for lad_code, entry in entries.items():
        if not entry.get("scraper_id") and entry.get("name", "").lower() == lowered:
            return resolve(lad_code)
    return None
