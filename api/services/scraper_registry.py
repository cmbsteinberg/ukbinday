"""Every council the API can scrape, keyed by its public council ID.

The public ID is the ONS LAD code (`E06000001`): what `/council/{postcode}`
returns, `/councils` lists, calendar URLs carry and ICS sidecars store.

- Council modules in `api/councils/` (a `SCRAPER` per module) are registered
  once per LAD in their `meta.lads`, so a module serving two councils (Adur &
  Worthing) answers to each code, with that LAD's GOV.UK page for deeplinks.
- Old `Source` classes in `api/scrapers/` that no module has replaced. One
  that `lad_lookup.json` wires to a LAD no module serves is registered under
  that LAD code too; the rest (none wired to any LAD today) keep their old
  scraper ID, since there is no LAD code to give them.

`api/councils/_aliases.json` is frozen: old scraper IDs and recoded LAD codes
-> the current LAD code. It resolves the IDs in calendar URLs and sidecars
written before the switch, and it is how the registry knows which old
scrapers a module has replaced. `get()` resolves; `meta.id` is the public ID
to cache and log under.
"""

from __future__ import annotations

import asyncio
import importlib
import inspect
import json
import logging
from collections.abc import Awaitable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from api.config import SCRAPER_TIMEOUT
from api.councils._base import Scraper, discovery, run

logger = logging.getLogger(__name__)

SCRAPERS_DIR = Path(__file__).parent.parent / "scrapers"
LAD_LOOKUP = Path(__file__).parent.parent / "data" / "lad_lookup.json"

# Query keys the frontend sends (besides `council`); `Address.label` arrives as `address`.
FRONTEND_PARAMS = ("uprn", "postcode", "address", "house_number", "street")
_FIELD_TO_PARAM = {"label": "address"}

# Scraper IDs whose module-level URL is served directly instead of scraped.
# Empty: ukbcd_google_public_calendar_council was the only member and was
# removed 2026-09-03 — its URL is the shared UKBCD *test* fixture, so every
# wired LAD got identical dummy bins on /calendar while /lookup 503d. The
# mechanism stays for future deeplink-shaped responses; re-add an ID here
# only with a per-council real target URL.
_PASSTHROUGH_SCRAPER_IDS: set[str] = set()


class ScraperTimeoutError(Exception):
    """Raised when a scraper exceeds the allowed timeout."""


class UnknownCouncilError(LookupError):
    """No council answers to this ID (e.g. a sidecar from a removed scraper)."""


@dataclass
class ScraperMeta:
    id: str
    title: str
    url: str
    required_params: list[str]
    optional_params: list[str]
    passthrough_url: str | None = None
    scraper: Scraper | None = None
    """The new-contract module serving this ID; None for an old `Source` scraper."""
    module: str = ""
    """The module name: `api.councils.<module>`, or `api.scrapers.<module>` for an old scraper."""
    lads: tuple[str, ...] = ()
    govuk_url: str | None = None
    """The council's waste page on GOV.UK's Local Links Manager, from `lad_lookup.json`.
    Deeplinks fall back to it (see api/services/deeplinks.py)."""

    @property
    def needs_browser(self) -> str | None:
        return self.scraper.needs_browser if self.scraper is not None else None


@dataclass
class HealthRecord:
    last_success: datetime | None = None
    last_error: str | None = None
    success_count: int = 0
    error_count: int = 0

    @property
    def status(self) -> str:
        if self.success_count == 0 and self.error_count == 0:
            return "unknown"
        return (
            "ok"
            if self.error_count == 0 or self.success_count > self.error_count
            else "error"
        )


def _module_params(scraper: Scraper) -> tuple[list[str], list[str]]:
    """`/councils` metadata from `requires`, in query-param names."""
    required = sorted(_FIELD_TO_PARAM.get(r, r) for r in scraper.requires)
    optional = [p for p in FRONTEND_PARAMS if p not in required]
    return required, optional


class ScraperRegistry:
    def __init__(self) -> None:
        self._scrapers: dict[str, ScraperMeta] = {}
        self._aliases: dict[str, str] = {}
        self._health: dict[str, HealthRecord] = {}

    @classmethod
    def build(cls) -> ScraperRegistry:
        registry = cls()
        registry._load_councils()
        registry._load_old_scrapers()
        return registry

    def _load_councils(self) -> None:
        """Register every council module under each LAD code it claims.

        A module that fails to import, two modules claiming one LAD, or a claim
        on an unknown LAD fails startup: each would silently unwire a council.
        """
        modules = {name: discovery.load(name) for name in discovery.module_names()}
        owner = discovery.by_lad(modules)
        lad_lookup = json.loads(LAD_LOOKUP.read_text())

        for lad, name in sorted(owner.items()):
            scraper = modules[name]
            required, optional = _module_params(scraper)
            self._scrapers[lad] = ScraperMeta(
                id=lad,
                title=scraper.meta.title,
                url=scraper.meta.url,
                required_params=required,
                optional_params=optional,
                scraper=scraper,
                module=name,
                lads=(lad,),
                govuk_url=lad_lookup.get(lad, {}).get("govuk_url"),
            )
        for name in sorted(set(modules) - set(owner.values())):
            logger.warning("Council module %s claims no LAD; not served", name)

        for alias, lad in discovery.aliases().items():
            if lad in self._scrapers:
                self._aliases[alias] = lad
            else:
                # The old scraper under this ID (if any) still loads under its own ID.
                logger.warning("Alias %s points at %s, which no council module serves", alias, lad)

        logger.info(
            "Loaded %d council modules for %d LADs (%d old IDs resolve to them)",
            len(set(owner.values())), len(owner), len(self._aliases),
        )

    def _load_old_scrapers(self) -> None:
        """Register the old `Source` scrapers no council module has replaced.

        One that `lad_lookup.json` wires to LADs no module serves is registered
        under those LAD codes, its old ID an alias; any other keeps its old ID.
        """
        lad_lookup = json.loads(LAD_LOOKUP.read_text())
        lads_by_id: dict[str, list[str]] = {}
        for lad, entry in sorted(lad_lookup.items()):
            if entry.get("scraper_id") and lad not in self._scrapers:
                lads_by_id.setdefault(entry["scraper_id"], []).append(lad)

        scraper_files = sorted(SCRAPERS_DIR.glob("*.py"))
        loaded = 0
        for path in scraper_files:
            name = path.stem
            if name in self._aliases:
                continue  # replaced by a council module
            try:
                module = importlib.import_module(f"api.scrapers.{name}")
                if not hasattr(module, "Source"):
                    continue

                title = getattr(module, "TITLE", name)
                url = getattr(module, "URL", "")
                passthrough_url = (
                    url if name in _PASSTHROUGH_SCRAPER_IDS else None
                )

                sig = inspect.signature(module.Source.__init__)
                required = []
                optional = []
                for param_name, param in sig.parameters.items():
                    if param_name == "self":
                        continue
                    if param.default is inspect.Parameter.empty:
                        required.append(param_name)
                    else:
                        optional.append(param_name)

                module.Source.__qualname__ = name
                lads = lads_by_id.get(name)
                for public_id in lads or [name]:
                    self._scrapers[public_id] = ScraperMeta(
                        id=public_id,
                        title=title,
                        url=url,
                        required_params=required,
                        optional_params=optional,
                        passthrough_url=passthrough_url,
                        module=name,
                        lads=(public_id,) if lads else (),
                        govuk_url=lad_lookup[public_id].get("govuk_url") if lads else None,
                    )
                if lads:
                    self._aliases[name] = lads[0]
                loaded += 1
            except Exception:
                logger.warning("Failed to load scraper %s", name, exc_info=True)

        logger.info("Loaded %d/%d old scrapers", loaded, len(scraper_files))

    def get(self, council_id: str) -> ScraperMeta | None:
        """The entry for a council ID, or for an old ID that resolves to one."""
        meta = self._scrapers.get(council_id)
        if meta is None and council_id in self._aliases:
            meta = self._scrapers.get(self._aliases[council_id])
        return meta

    def canonical_id(self, council_id: str) -> str:
        """The public ID an old ID resolves to; unknown IDs come back unchanged."""
        meta = self.get(council_id)
        return meta.id if meta is not None else council_id

    def list_all(self) -> list[ScraperMeta]:
        return list(self._scrapers.values())

    async def invoke(self, council_id: str, params: dict) -> list[Any]:
        meta = self.get(council_id)
        if meta is None:
            raise UnknownCouncilError(f"No council answers to {council_id!r}")
        call: Awaitable[list[Any]]
        if meta.scraper is not None:
            call = run(meta.scraper, params)
        else:
            module = importlib.import_module(f"api.scrapers.{meta.module}")
            accepted = set(meta.required_params + meta.optional_params)
            call = module.Source(**{k: v for k, v in params.items() if k in accepted}).fetch()
        try:
            return await asyncio.wait_for(call, timeout=SCRAPER_TIMEOUT)
        except asyncio.TimeoutError:
            raise ScraperTimeoutError(
                f"Scraper {council_id} timed out after {SCRAPER_TIMEOUT}s"
            )

    def record_success(self, council_id: str) -> None:
        record = self._health.setdefault(self.canonical_id(council_id), HealthRecord())
        record.last_success = datetime.now()
        record.success_count += 1

    def record_failure(self, council_id: str, error: str) -> None:
        record = self._health.setdefault(self.canonical_id(council_id), HealthRecord())
        record.last_error = error
        record.error_count += 1

    def get_health(self, council_id: str) -> HealthRecord:
        return self._health.get(self.canonical_id(council_id), HealthRecord())
