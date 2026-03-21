from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

from src.address_lookup.address_lookup import AddressLookup
from src.api.routes import router
from src.api.scraper_registry import ScraperRegistry
from src.api.views import index_page

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Building scraper registry...")
    app.state.registry = ScraperRegistry.build()
    logger.info("Registry ready: %d scrapers", len(app.state.registry.list_all()))

    app.state.address_lookup = AddressLookup()

    # Redis (optional)
    redis_url = os.getenv("REDIS_URL")
    if redis_url:
        try:
            import redis.asyncio as aioredis

            app.state.redis = aioredis.from_url(redis_url)
            await app.state.redis.ping()
            logger.info("Redis connected at %s", redis_url)
        except Exception:
            logger.warning("Redis unavailable, rate limiting disabled", exc_info=True)
            app.state.redis = None
    else:
        app.state.redis = None
        logger.info("No REDIS_URL set, rate limiting disabled")

    yield

    # Shutdown
    if getattr(app.state, "address_lookup", None):
        await app.state.address_lookup.close()
    if getattr(app.state, "redis", None):
        await app.state.redis.aclose()


app = FastAPI(
    title="UK Bin Collection API",
    description="Look up bin collection schedules for UK councils",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/api/v1/docs",
    redoc_url="/api/v1/redoc",
    openapi_url="/api/v1/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

# Mount router at both paths — internal and versioned public API
app.include_router(router, prefix="/api")
app.include_router(router, prefix="/api/v1")


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def landing_page():
    return index_page()
