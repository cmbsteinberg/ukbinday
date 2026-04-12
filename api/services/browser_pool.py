"""Shared Playwright browser pool.

Manages a single Playwright instance + Chromium browser that all Playwright
scrapers share.  Each scraper request gets an isolated BrowserContext (separate
cookies, storage, cache) via ``new_context()``, so scrapers can't interfere
with each other — but they all share the same browser process, saving ~500 MB
RAM per concurrent request compared to launching separate browsers.
"""

from __future__ import annotations

import asyncio
import logging

from playwright.async_api import Browser, BrowserContext, Playwright, async_playwright

logger = logging.getLogger(__name__)

# Module-level singleton — set by start() / stop(), read by scrapers.
_instance: BrowserPool | None = None


class BrowserPool:
    def __init__(self) -> None:
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        """Launch the shared Playwright + Chromium browser."""
        async with self._lock:
            if self._browser is not None:
                return
            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(headless=True)
            logger.info("BrowserPool: shared Chromium launched (pid %s)", self._browser)

    async def stop(self) -> None:
        """Shut down the shared browser and Playwright."""
        async with self._lock:
            if self._browser:
                await self._browser.close()
                self._browser = None
            if self._playwright:
                await self._playwright.stop()
                self._playwright = None
            logger.info("BrowserPool: shut down")

    async def new_context(self) -> BrowserContext:
        """Create a new isolated browser context.

        The caller is responsible for closing the context when done
        (``await context.close()``).
        """
        if not self._browser:
            raise RuntimeError("BrowserPool not started — call await pool.start() first")
        return await self._browser.new_context()


async def start() -> BrowserPool:
    """Start the module-level singleton pool."""
    global _instance
    if _instance is None:
        _instance = BrowserPool()
    await _instance.start()
    return _instance


async def stop() -> None:
    """Stop the module-level singleton pool."""
    global _instance
    if _instance is not None:
        await _instance.stop()
        _instance = None


def get() -> BrowserPool:
    """Get the running pool.  Raises if not started."""
    if _instance is None:
        raise RuntimeError("BrowserPool not started")
    return _instance
