from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.templating import Jinja2Templates

from api import config
from api.logging_config import setup_logging
from api.routes import router as api_router
from api.services.blob_store import from_config
from api.services.council_lookup import CouncilLookup
from api.services.ics_cache import IcsCache
from api.services.refresh_job import RefreshJob
from api.services.scrape_orchestrator import ScrapeHTTPException
from api.services.scraper_registry import ScraperRegistry

setup_logging()

_TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
_STATIC_DIR = Path(__file__).resolve().parent / "static"
_templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Building scraper registry...")
    app.state.registry = ScraperRegistry.build()
    logger.info("Registry ready: %d council IDs", len(app.state.registry.list_all()))

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

    app.state.ics_cache = IcsCache(from_config(), canonical_id=app.state.registry.canonical_id)

    app.state.refresh_job = None
    app.state.refresh_task = None
    if config.RUN_REFRESH_JOB:
        job = RefreshJob(
            app.state.ics_cache,
            app.state.registry,
            app.state.redis,
            concurrency=config.ICS_REFRESH_CONCURRENCY,
            failure_threshold=config.ICS_FAILURE_THRESHOLD,
        )
        app.state.refresh_job = job
        app.state.refresh_task = asyncio.create_task(
            job.run_forever(hour_utc=config.ICS_REFRESH_HOUR_UTC)
        )

    yield

    # Shutdown
    if getattr(app.state, "refresh_task", None):
        app.state.refresh_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await app.state.refresh_task

    if getattr(app.state, "council_lookup", None):
        await app.state.council_lookup.close()
    if getattr(app.state, "redis", None):
        await app.state.redis.aclose()


app = FastAPI(
    title="UK Bin Collection API",
    description="Look up bin collection schedules for UK councils",
    version="2.0.0",
    lifespan=lifespan,
    docs_url="/api/v2/docs",
    redoc_url="/api/v2/redoc",
    openapi_url="/api/v2/openapi.json",
)

# Calendars are mostly repeated VEVENT boilerplate; gzip cuts them ~10x, which is what
# counts against Vercel Hobby's Fast Origin Transfer allowance (VERCEL.md, "Will it be free")
app.add_middleware(GZipMiddleware, minimum_size=1000)
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_methods=["GET"],
    allow_headers=["*"],
)


@app.exception_handler(ScrapeHTTPException)
async def scrape_http_exception(request: Request, exc: ScrapeHTTPException):
    """The usual {"detail": ...} body, plus the council's address list when it offered one."""
    body: dict = {"detail": exc.detail}
    if exc.suggestions:
        body["suggestions"] = exc.suggestions
    return JSONResponse(body, status_code=exc.status_code, headers=exc.headers)


request_logger = logging.getLogger("api.requests")


@app.middleware("http")
async def log_requests(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:12]
    request.state.request_id = request_id
    start = time.time()
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    duration_ms = round((time.time() - start) * 1000)
    request_logger.info(
        "%s %s %d %dms",
        request.method,
        request.url.path,
        response.status_code,
        duration_ms,
        extra={
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
            "status_code": response.status_code,
            "duration_ms": duration_ms,
            "client_ip": request.headers.get("X-Forwarded-For", "")
            .split(",")[0]
            .strip()
            or (request.client.host if request.client else "unknown"),
        },
    )
    # In dev, prevent stale static file caching so changes appear immediately
    if request.url.path.startswith("/static") and os.getenv("ENV") != "production":
        response.headers["Cache-Control"] = "no-cache"
    # Security headers
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["Strict-Transport-Security"] = (
        "max-age=31536000; includeSubDomains"
    )
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    # If Redis is available, increment a counter for analytics
    redis_client = getattr(request.app.state, "redis", None)
    if redis_client and request.url.path.startswith("/api"):
        try:
            await redis_client.hincrby("api:request_counts", request.url.path, 1)
        except Exception:
            logger.debug("Redis analytics increment failed", exc_info=True)
    return response


# API routes
app.include_router(api_router, prefix="/api/v2")


# Static files
app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")


# Frontend pages
@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def landing_page(request: Request):
    return _templates.TemplateResponse(
        request,
        "index.html",
        {"turnstile_site_key": config.TURNSTILE_SITE_KEY},
    )


@app.get("/coverage", response_class=HTMLResponse, include_in_schema=False)
async def coverage_page(request: Request):
    return _templates.TemplateResponse(request, "coverage.html")


@app.get("/api-docs", response_class=HTMLResponse, include_in_schema=False)
async def api_docs_page(request: Request):
    return _templates.TemplateResponse(request, "api-docs.html")


@app.get("/about", response_class=HTMLResponse, include_in_schema=False)
async def about_page(request: Request):
    return _templates.TemplateResponse(request, "about.html")


@app.get("/sitemap.xml", include_in_schema=False)
async def sitemap():
    from fastapi.responses import Response

    pages = ["/", "/coverage", "/api-docs", "/about"]
    host = config.BASE_URL.rstrip("/")
    if not host:
        logger.warning("BASE_URL not set, sitemap will use relative URLs")
    urls = "\n".join(f"  <url><loc>{host}{p}</loc></url>" for p in pages)
    xml = f'<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n{urls}\n</urlset>'
    return Response(content=xml, media_type="application/xml")


# uv run uvicorn api.main:app --reload
# docker compose up --build
