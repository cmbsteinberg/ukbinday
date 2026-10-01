"""Every council the API can scrape, keyed by the ID the frontend sends.

Two kinds of entry during the migration:

- New-contract modules in `api/councils/` (a `SCRAPER` per module). Each
  serves the LADs in its `meta.lads`; for those LADs it wins over any old
  scraper. Its public ID is the scraper ID `lad_lookup.json` gives its LADs
  (what `/council/{postcode}` returns and calendar URLs carry), falling back
  to its first LAD code for a LAD that never had one.
- Old `Source` classes in `api/scrapers/`, for IDs no module has taken over.

Any other name for a module resolves to it: an old scraper ID in
`api/councils/_aliases.json` (permanent, so old calendar URLs and cache
sidecars keep working) or one of its LAD codes. `get()` resolves; `meta.id`
is the canonical ID to cache and log under.
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
    module: str | None = None
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
        registry._load_old_scrapers()
        registry._load_councils()
        return registry

    def _load_old_scrapers(self) -> None:
        govuk_by_id: dict[str, str] = {}
        for entry in json.loads(LAD_LOOKUP.read_text()).values():
            if entry.get("scraper_id") and entry.get("govuk_url"):
                govuk_by_id.setdefault(entry["scraper_id"], entry["govuk_url"])
        scraper_files = sorted(SCRAPERS_DIR.glob("*.py"))
        loaded = 0
        for path in scraper_files:
            name = path.stem
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
                self._scrapers[name] = ScraperMeta(
                    id=name,
                    title=title,
                    url=url,
                    required_params=required,
                    optional_params=optional,
                    passthrough_url=passthrough_url,
                    govuk_url=govuk_by_id.get(name),
                )
                loaded += 1
            except Exception:
                logger.warning("Failed to load scraper %s", name, exc_info=True)

        logger.info("Loaded %d/%d old scrapers", loaded, len(scraper_files))

    def _load_councils(self) -> None:
        """Register every council module, shadowing the old scrapers it replaces.

        A module that fails to import, two modules claiming one LAD, or a claim
        on an unknown LAD fails startup: each would silently unwire a council.
        """
        modules = {name: discovery.load(name) for name in discovery.module_names()}
        owner = discovery.by_lad(modules)
        lad_lookup = json.loads(LAD_LOOKUP.read_text())

        public: dict[str, str] = {}  # module -> public ID
        for lad in sorted(owner):
            name = owner[lad]
            sid = (lad_lookup.get(lad) or {}).get("scraper_id")
            if name not in public:
                public[name] = sid or lad
            elif sid and sid != public[name]:
                # One module whose LADs carry different scraper IDs: the others alias it.
                self._aliases[sid] = public[name]

        for name, scraper in modules.items():
            if name not in public:
                logger.warning("Council module %s claims no LAD; not served", name)
                continue
            sid = public[name]
            required, optional = _module_params(scraper)
            govuk = next(
                (url for lad in scraper.meta.lads if (url := lad_lookup.get(lad, {}).get("govuk_url"))),
                None,
            )
            self._scrapers[sid] = ScraperMeta(
                id=sid,
                title=scraper.meta.title,
                url=scraper.meta.url,
                required_params=required,
                optional_params=optional,
                scraper=scraper,
                module=name,
                lads=scraper.meta.lads,
                govuk_url=govuk,
            )
            for lad in scraper.meta.lads:
                self._aliases[lad] = sid

        for alias, lad in discovery.aliases().items():
            name = owner.get(lad)
            if name is None:
                logger.warning("Alias %s points at %s, which no council module serves", alias, lad)
                continue
            if alias in public.values():
                continue  # a module's own public ID: lad_lookup.json's current wiring wins
            # The module wins: an old scraper under this ID is shadowed.
            self._scrapers.pop(alias, None)
            self._aliases[alias] = public[name]

        logger.info(
            "Loaded %d council modules (%d LADs, %d aliases); %d IDs in total",
            len(public), len(owner), len(self._aliases), len(self._scrapers),
        )

    def get(self, council_id: str) -> ScraperMeta | None:
        """The entry for an ID or any alias of it."""
        meta = self._scrapers.get(council_id)
        if meta is None and council_id in self._aliases:
            meta = self._scrapers.get(self._aliases[council_id])
        return meta

    def canonical_id(self, council_id: str) -> str:
        """The ID an alias resolves to; unknown IDs come back unchanged."""
        meta = self.get(council_id)
        return meta.id if meta is not None else council_id

    def list_all(self) -> list[ScraperMeta]:
        return list(self._scrapers.values())

    async def invoke(self, council_id: str, params: dict) -> list[Any]:
        meta = self.get(council_id)
        call: Awaitable[list[Any]]
        if meta is not None and meta.scraper is not None:
            call = run(meta.scraper, params)
        else:
            module = importlib.import_module(f"api.scrapers.{meta.id if meta else council_id}")
            if meta:
                accepted = set(meta.required_params + meta.optional_params)
                filtered = {k: v for k, v in params.items() if k in accepted}
            else:
                filtered = params
            call = module.Source(**filtered).fetch()
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
