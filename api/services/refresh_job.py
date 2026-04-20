from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from api import config
from api.services.ics_cache import IcsCache
from api.services.scraper_registry import ScraperRegistry

logger = logging.getLogger(__name__)


@dataclass
class RefreshStats:
    scanned: int = 0
    refreshed: int = 0
    skipped: int = 0
    failed: int = 0
    deleted: int = 0
    duration_s: float = 0.0


class RefreshJob:
    def __init__(
        self,
        cache: IcsCache,
        registry: ScraperRegistry,
        redis_client=None,
        *,
        concurrency: int = 4,
        failure_threshold: int = 14,
    ) -> None:
        self.cache = cache
        self.registry = registry
        self.redis = redis_client
        self.concurrency = concurrency
        self.failure_threshold = failure_threshold
        self.last_run: datetime | None = None
        self.last_stats: RefreshStats | None = None

    def _eligible(self, next_collection: date | None, today: date) -> bool:
        if next_collection is None:
            return True
        return next_collection <= today + timedelta(days=1)

    async def run_once(self) -> RefreshStats:
        stats = RefreshStats()
        start = time.monotonic()
        today = date.today()
        sem = asyncio.Semaphore(self.concurrency)

        async def handle(entry) -> None:
            async with sem:
                try:
                    collections = await self.registry.invoke(entry.scraper, entry.params)
                    self.registry.record_success(entry.scraper)
                    await self.cache.write(
                        entry.uprn, entry.scraper, entry.params, collections
                    )
                    stats.refreshed += 1
                except Exception as exc:
                    self.registry.record_failure(entry.scraper, str(exc))
                    await self.cache.record_failure(entry.uprn, str(exc))
                    stats.failed += 1
                    new_entry = await self.cache.read(entry.uprn)
                    if (
                        new_entry is not None
                        and new_entry.consecutive_failures >= self.failure_threshold
                    ):
                        await self.cache.delete(entry.uprn)
                        stats.deleted += 1
                    logger.warning(
                        "Refresh failed for %s (%s): %s", entry.uprn, entry.scraper, exc
                    )

        tasks = []
        for entry in self.cache.iter_entries():
            stats.scanned += 1
            if not self._eligible(entry.next_collection, today):
                stats.skipped += 1
                continue
            tasks.append(asyncio.create_task(handle(entry)))

        if tasks:
            await asyncio.gather(*tasks)

        stats.duration_s = round(time.monotonic() - start, 2)
        self.last_run = datetime.now(UTC)
        self.last_stats = stats
        self._write_heartbeat(stats)
        logger.info("Refresh pass complete: %s", asdict(stats))
        return stats

    def _write_heartbeat(self, stats: RefreshStats) -> None:
        try:
            path = Path(config.DATA_DIR) / ".worker_heartbeat"
            path.write_text(
                json.dumps(
                    {
                        "last_run": self.last_run.isoformat() if self.last_run else None,
                        "stats": asdict(stats),
                    }
                )
            )
        except OSError:
            logger.debug("Failed to write heartbeat", exc_info=True)

    async def run_forever(self, *, hour_utc: int = 3) -> None:
        while True:
            now = datetime.now(UTC)
            target = now.replace(hour=hour_utc, minute=0, second=0, microsecond=0)
            if target <= now:
                target = target + timedelta(days=1)
            wait_s = (target - now).total_seconds()
            logger.info("Next refresh pass at %s (%.0fs)", target.isoformat(), wait_s)
            try:
                await asyncio.sleep(wait_s)
            except asyncio.CancelledError:
                raise
            try:
                await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Refresh pass crashed")


async def _main() -> None:
    from api.logging_config import setup_logging

    setup_logging()
    cache = IcsCache(Path(config.DATA_DIR) / config.ICS_CACHE_SUBDIR)
    registry = ScraperRegistry.build()
    redis_client = None
    import os

    redis_url = os.getenv("REDIS_URL")
    if redis_url:
        try:
            import redis.asyncio as aioredis

            redis_client = aioredis.from_url(redis_url)
            await redis_client.ping()
        except Exception:
            logger.warning("Redis unavailable for worker", exc_info=True)
            redis_client = None

    job = RefreshJob(
        cache,
        registry,
        redis_client,
        concurrency=config.ICS_REFRESH_CONCURRENCY,
        failure_threshold=config.ICS_FAILURE_THRESHOLD,
    )
    await job.run_forever(hour_utc=config.ICS_REFRESH_HOUR_UTC)


if __name__ == "__main__":
    asyncio.run(_main())
