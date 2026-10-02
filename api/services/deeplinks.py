"""Deeplink targets for councils with no scraper.

A deeplink is a structured "check on the council website instead" response:
a URL, a human-readable reason and a ``Blocker`` naming what's in the way. It
covers every unwired LAD in ``lad_lookup.json`` (``scraper_id: null``: no
council module claims it), with the reason and blocker from
``pipeline/lad_overrides.json`` where recorded.

URL priority: council bin page (``url``) > GOV.UK page (``govuk_url``).
Reason: the entry's ``status`` line, or a generic fallback; blocker: the
entry's ``blocker``, else NOT_SUPPORTED.

Wired councils get the same response shape in two cases (see
``scrape_orchestrator``): the scraper raised ``NeedsBrowser``
(``for_needs_browser``: scraper URL first), or the council's site failed
with nothing cached (``for_upstream_failure``: GOV.UK first).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from api.councils._base import Blocker

_DATA_DIR = Path(__file__).parent.parent / "data"
_LAD_JSON = _DATA_DIR / "lad_lookup.json"

_GENERIC_REASON = "This council isn't supported for automatic lookups yet."


@dataclass(frozen=True)
class Deeplink:
    lad_code: str
    council_name: str
    url: str
    reason: str
    blocker: Blocker


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
        blocker=Blocker(entry.get("blocker") or Blocker.NOT_SUPPORTED),
    )


def _for_scraper(meta, url: str | None, reason: str, blocker: Blocker) -> Deeplink | None:
    if not url:
        return None
    return Deeplink(
        lad_code=meta.lads[0] if meta.lads else "",
        council_name=meta.title,
        url=url,
        reason=reason or _GENERIC_REASON,
        blocker=blocker,
    )


def for_needs_browser(meta, reason: str, blocker: Blocker | None = None) -> Deeplink | None:
    """The deeplink for a wired council whose scraper raised ``NeedsBrowser``.

    ``meta`` is the registry's ``ScraperMeta``. URL: the scraper's ``url``
    (a council module's ``meta.url`` points at its lookup page), else the
    LAD's GOV.UK page. Reason: the scraper's. Blocker: the exception's, else
    the module's, else BROWSER_ONLY.
    """
    blocker = blocker or meta.blocker or Blocker.BROWSER_ONLY
    return _for_scraper(meta, meta.url or meta.govuk_url, reason, blocker)


def for_upstream_failure(meta) -> Deeplink | None:
    """The deeplink for a wired council whose site failed (down, erroring, timed out).

    URL: the LAD's GOV.UK page first (Local Links Manager is maintained
    centrally, so it outlives a council's site reshuffle), else the scraper's
    ``url``. A module marked BOT_PROTECTION (its site blocks our host) says so;
    any other failure is SITE_DOWN.
    """
    if meta.blocker == Blocker.BOT_PROTECTION:
        blocker = Blocker.BOT_PROTECTION
        reason = (
            f"{meta.title}'s website blocks automated lookups from our servers; "
            "check your bin day on the council's site."
        )
    else:
        blocker = Blocker.SITE_DOWN
        reason = (
            f"{meta.title}'s website isn't responding right now; "
            "check your bin day on the council's site."
        )
    return _for_scraper(meta, meta.govuk_url or meta.url, reason, blocker)


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
