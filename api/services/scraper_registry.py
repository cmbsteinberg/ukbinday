from __future__ import annotations

import asyncio
import importlib
import inspect
import json
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from api.compat.hacs import Collection

logger = logging.getLogger(__name__)

SCRAPERS_DIR = Path(__file__).parent.parent / "scrapers"
DISABLED_PATH = Path(__file__).parent.parent / "data" / "disabled_scrapers.json"
SCRAPER_TIMEOUT = 30  # seconds


class ScraperTimeoutError(Exception):
    """Raised when a scraper exceeds the allowed timeout."""


@dataclass
class ScraperMeta:
    id: str
    title: str
    url: str
    required_params: list[str]
    optional_params: list[str]


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


class ScraperRegistry:
    def __init__(self) -> None:
        self._scrapers: dict[str, ScraperMeta] = {}
        self._health: dict[str, HealthRecord] = {}

    @classmethod
    def build(cls) -> ScraperRegistry:
        registry = cls()

        # Load disabled scrapers list
        disabled: set[str] = set()
        if DISABLED_PATH.exists():
            try:
                data = json.loads(DISABLED_PATH.read_text())
                disabled = set(data.get("disabled", []))
                logger.info(
                    "Loaded %d disabled scrapers from %s",
                    len(disabled),
                    DISABLED_PATH.name,
                )
            except Exception:
                logger.warning("Could not read %s", DISABLED_PATH, exc_info=True)

        scraper_files = sorted(SCRAPERS_DIR.glob("*.py"))
        loaded = 0
        skipped = 0
        for path in scraper_files:
            name = path.stem
            if name in disabled:
                skipped += 1
                continue
            try:
                module = importlib.import_module(f"api.scrapers.{name}")
                if not hasattr(module, "Source"):
                    continue

                title = getattr(module, "TITLE", name)
                url = getattr(module, "URL", "")

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
                registry._scrapers[name] = ScraperMeta(
                    id=name,
                    title=title,
                    url=url,
                    required_params=required,
                    optional_params=optional,
                )
                loaded += 1
            except Exception:
                logger.warning("Failed to load scraper %s", name, exc_info=True)

        if skipped:
            logger.info(
                "Loaded %d/%d scrapers (%d disabled)",
                loaded,
                len(scraper_files),
                skipped,
            )
        else:
            logger.info("Loaded %d/%d scrapers", loaded, len(scraper_files))
        return registry

    def get(self, council_id: str) -> ScraperMeta | None:
        return self._scrapers.get(council_id)

    def list_all(self) -> list[ScraperMeta]:
        return list(self._scrapers.values())

    async def invoke(self, council_id: str, params: dict) -> list[Collection]:
        module = importlib.import_module(f"api.scrapers.{council_id}")
        meta = self._scrapers.get(council_id)
        if meta:
            accepted = set(meta.required_params + meta.optional_params)
            filtered = {k: v for k, v in params.items() if k in accepted}
        else:
            filtered = params
        source = module.Source(**filtered)
        try:
            return await asyncio.wait_for(source.fetch(), timeout=SCRAPER_TIMEOUT)
        except asyncio.TimeoutError:
            raise ScraperTimeoutError(
                f"Scraper {council_id} timed out after {SCRAPER_TIMEOUT}s"
            )

    def record_success(self, council_id: str) -> None:
        record = self._health.setdefault(council_id, HealthRecord())
        record.last_success = datetime.now()
        record.success_count += 1

    def record_failure(self, council_id: str, error: str) -> None:
        record = self._health.setdefault(council_id, HealthRecord())
        record.last_error = error
        record.error_count += 1

    def get_health(self, council_id: str) -> HealthRecord:
        return self._health.get(council_id, HealthRecord())
