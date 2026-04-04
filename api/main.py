from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from api.routes import router as api_router
from api.services.council_lookup import CouncilLookup
from api.services.scraper_registry import ScraperRegistry

_TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
_STATIC_DIR = Path(__file__).resolve().parent / "static"

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Building scraper registry...")
    app.state.registry = ScraperRegistry.build()
    logger.info("Registry ready: %d scrapers", len(app.state.registry.list_all()))

    app.state.council_lookup = CouncilLookup()
    if not app.state.council_lookup.parquet_loaded:
        logger.error(
            "STARTUP WARNING: postcode_lookup.parquet not loaded — "
            "postcode-to-council lookups will not work"
        )
    if not app.state.council_lookup.lad_loaded:
        logger.error(
            "STARTUP WARNING: lad_lookup.json not loaded — "
            "council metadata will be unavailable"
        )

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
    if getattr(app.state, "council_lookup", None):
        await app.state.council_lookup.close()
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

# API routes
app.include_router(api_router, prefix="/api")
app.include_router(api_router, prefix="/api/v1")


# Static files
app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")


# Frontend pages
@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def landing_page():
    return (_TEMPLATES_DIR / "index.html").read_text()


@app.get("/coverage", response_class=HTMLResponse, include_in_schema=False)
async def coverage_page():
    return (_TEMPLATES_DIR / "coverage.html").read_text()


@app.get("/api-docs", response_class=HTMLResponse, include_in_schema=False)
async def api_docs_page():
    return (_TEMPLATES_DIR / "api-docs.html").read_text()
