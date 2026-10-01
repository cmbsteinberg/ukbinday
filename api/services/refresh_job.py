from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, timedelta

from api import config
from api.services.blob_store import from_config
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
    deferred: int = 0  # skipped for the deadline; counts unread sidecars too, so an upper bound on the due ones
    shard: int = 0
    of: int = 1
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

    async def run_once(
        self, *, shard: int = 0, of: int = 1, deadline: float | None = None
    ) -> RefreshStats:
        """Refresh the due UPRNs of shard `shard` of `of` (those with
        `int(uprn) % of == shard`). `deadline` is a `time.monotonic()` value:
        nothing new is queued after it, in-flight scrapes finish, and the rest
        are counted as `deferred` and left for the next pass."""
        stats = RefreshStats(shard=shard, of=of)
        start = time.monotonic()
        today = date.today()

        queue: asyncio.Queue = asyncio.Queue()

        async def worker() -> None:
            while True:
                entry = await queue.get()
                try:
                    if entry is None:
                        return
                    if deadline is not None and time.monotonic() >= deadline:
                        stats.deferred += 1  # queued, but too late to start
                        continue
                    await self._refresh_one(entry, stats)
                finally:
                    queue.task_done()

        workers = [asyncio.create_task(worker()) for _ in range(self.concurrency)]

        uprns = await self.cache.sidecar_uprns(shard, of)
        for i, uprn in enumerate(uprns):
            if deadline is not None and time.monotonic() >= deadline:
                stats.deferred += len(uprns) - i
                break
            entry = await self.cache.read_sidecar(uprn)
            if entry is None:
                continue
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
        await self._write_heartbeat(stats, len(uprns))
        logger.info("Refresh pass complete: %s", asdict(stats))
        return stats

    async def _write_heartbeat(self, stats: RefreshStats, entries: int) -> None:
        try:
            await self.cache.write_heartbeat(
                stats.shard, stats.of, entries, asdict(stats)
            )
        except Exception:
            logger.warning("Failed to write heartbeat", exc_info=True)

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
    cache = IcsCache(from_config(), canonical_id=registry.canonical_id)
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
