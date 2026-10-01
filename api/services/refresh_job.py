from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from api import config
from api.services.ics_cache import IcsCache
from api.services.scrape_lock import acquire, release
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

    def _eligible(self, entry, today: date) -> bool:
        if entry.next_collection is None:
            return True
        if entry.next_collection > today + timedelta(days=1):
            return False
        if entry.last_success is not None:
            last = entry.last_success
            if last.tzinfo is None:
                last = last.replace(tzinfo=UTC)
            age = datetime.now(UTC) - last
            if age < timedelta(hours=config.ICS_REFRESH_MIN_AGE_HOURS):
                return False
        return True

    async def _refresh_one(self, entry, stats: RefreshStats) -> None:
        lock_acquired = await acquire(self.redis, entry.uprn)
        if not lock_acquired:
            stats.skipped += 1
            return
        try:
            try:
                # entry.scraper may be an old scraper ID from before the switch to LAD
                # codes: invoke resolves it and the write stores the LAD code, so the
                # sidecar is migrated on its first successful refresh. An ID nothing
                # answers to raises UnknownCouncilError and ages out as a failure.
                collections = await self.registry.invoke(entry.scraper, entry.params)
                self.registry.record_success(entry.scraper)
                await self.cache.write(
                    entry.uprn,
                    self.registry.canonical_id(entry.scraper),
                    entry.params,
                    collections,
                )
                stats.refreshed += 1
            except Exception as exc:
                self.registry.record_failure(entry.scraper, str(exc))
                await self.cache.record_failure(
                    entry.uprn,
                    str(exc),
                    scraper_id=entry.scraper,
                    params=entry.params,
                )
                stats.failed += 1
                new_entry = await self.cache.read(entry.uprn)
                if (
                    new_entry is not None
                    and new_entry.consecutive_failures >= self.failure_threshold
                ):
                    await self.cache.delete(entry.uprn)
                    stats.deleted += 1
                logger.warning(
                    "Refresh failed for %s (%s): %s",
                    entry.uprn,
                    entry.scraper,
                    exc,
                )
        finally:
            await release(self.redis, entry.uprn)

    async def run_once(self) -> RefreshStats:
        stats = RefreshStats()
        start = time.monotonic()
        today = date.today()

        queue: asyncio.Queue = asyncio.Queue()

        async def worker() -> None:
            while True:
                entry = await queue.get()
                try:
                    if entry is None:
                        return
                    await self._refresh_one(entry, stats)
                finally:
                    queue.task_done()

        workers = [asyncio.create_task(worker()) for _ in range(self.concurrency)]

        for entry in self.cache.iter_entries():
            stats.scanned += 1
            if not self._eligible(entry, today):
                stats.skipped += 1
                continue
            await queue.put(entry)

        await queue.join()
        for _ in workers:
            await queue.put(None)
        await asyncio.gather(*workers, return_exceptions=True)

        stats.duration_s = round(time.monotonic() - start, 2)
        self.last_run = datetime.now(UTC)
        self.last_stats = stats
        self._write_heartbeat(stats)
        logger.info("Refresh pass complete: %s", asdict(stats))
        return stats

    def _write_heartbeat(self, stats: RefreshStats) -> None:
        try:
            path = Path(config.DATA_DIR) / ".worker_heartbeat"
            payload = json.dumps(
                {
                    "last_run": self.last_run.isoformat() if self.last_run else None,
                    "stats": asdict(stats),
                }
            ).encode()
            tmp = path.with_suffix(path.suffix + ".tmp")
            tmp.write_bytes(payload)
            os.replace(tmp, path)
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
    registry = ScraperRegistry.build()
    cache = IcsCache(
        Path(config.DATA_DIR) / config.ICS_CACHE_SUBDIR,
        canonical_id=registry.canonical_id,
    )
    redis_client = None
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
    if os.getenv("RUN_REFRESH_NOW") == "1":
        await job.run_once()
    await job.run_forever(hour_utc=config.ICS_REFRESH_HOUR_UTC)


if __name__ == "__main__":
    asyncio.run(_main())
