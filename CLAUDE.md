# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

UK Bin Collection API -- a FastAPI service that scrapes UK council websites to return bin/waste collection schedules. About 350 council scrapers live in `api/scrapers/`, patched from two upstream repos (hacs_waste_collection_schedule and UKBinCollectionData) to work as async API endpoints.

## Commands

```bash
# Run dev server
uv run uvicorn api.main:app --reload

# Run all tests
uv run pytest tests/ -v

# Fast smoke tests (syntax, imports, app boot, registry -- runs as pre-commit hook)
uv run pytest tests/test_ci.py -v

# Frontend/API surface tests (fast, no external calls)
uv run pytest tests/test_frontend.py -v

# Integration tests (requests-based scrapers, hits live council sites, slow)
uv run pytest tests/test_integration.py -v

# Playwright integration tests (browser-based scrapers, very heavy)
uv run pytest tests/test_playwright.py -v

# Run a single scraper test by keyword
uv run pytest tests/test_integration.py -v -k "aberdeen"

# Docker stack tests
uv run pytest tests/test_deploy.py -v

# Lint Python (ruff -- excludes api/scrapers/)
uv run ruff check --fix

# Lint JS/JSON (biome)
npx @biomejs/biome check --write

# Sync and patch scrapers from upstream repos
pipeline/hacs/sync.sh      # hacs_waste_collection_schedule (primary)
pipeline/ukbcd/sync.sh     # UKBinCollectionData (fallback)

# Regenerate test_cases.json from scraper TEST_CASES
uv run python -m pipeline.hacs.generate_test_lookup   # hacs scrapers
uv run python -m pipeline.ukbcd.generate_test_lookup   # ukbcd scrapers (merges into same file)

# Regenerate admin_scraper_lookup.json (council domain to scraper ID mapping)
uv run python -m scripts.generate_admin_lookup

# Regenerate postcode/LAD lookup data
uv run python -m scripts.lookup.create_lookup_table

# Regenerate coverage map
uv run python -m scripts.coverage.generate_coverage_map

# Docker
docker compose up --build
```

## Architecture

**API layer** (`api/`):
- `main.py` -- FastAPI app with lifespan managing `ScraperRegistry`, `AddressLookup`, and optional Redis
- `routes.py` -- All endpoints: `/api/v1/addresses/{postcode}`, `/api/v1/council/{postcode}`, `/api/v1/lookup/{uprn}`, `/api/v1/calendar/{uprn}`, `/api/v1/councils`, `/api/v1/health`. Routes are mounted under both `/api` and `/api/v1`
- `services/scraper_registry.py` -- Dynamically imports all `api/scrapers/*.py` at startup, introspects `Source.__init__` signatures for required/optional params, and dispatches `await source.fetch()` calls
- `services/address_lookup.py` -- Resolves postcodes to addresses (via Mid Suffolk API) and to local authorities (via local parquet lookup with ibis/duckdb)
- `services/models.py` -- Pydantic response models
- `services/rate_limiting.py` -- Redis-backed rate limiter (disabled when no `REDIS_URL`)
- `data/admin_scraper_lookup.json` -- Council domain to scraper ID mapping
- `data/lad_lookup.json` -- LAD code to council name, URL, and scraper ID
- `data/postcode_lookup.parquet` -- 1.6M postcodes mapped to LAD codes for fast local lookup
- `templates/` -- HTML pages: landing (`index.html`), coverage map (`coverage.html`), API docs (`api-docs.html`)
- `static/` -- Frontend JS (`app.js`, `address_lookup.js`), coverage GeoJSON, Leaflet map

**Scrapers** (`api/scrapers/`):
- About 350 files (flat directory), one per council. Each defines `TITLE`, `URL`, `TEST_CASES`, and a `Source` class with `async def fetch() -> list[Collection]`
- About 240 from hacs (named `*_gov_uk.py`), about 110 from ukbcd (named `robbrad_*.py`)
- Excluded from ruff linting (configured in `pyproject.toml`)

**Compat shims** (`api/compat/`):
- `hacs/` -- Minimal types/helpers synced from hacs upstream: `Collection`, `CollectionBase`, `CollectionGroup`, `ICS`, `SSLError`. Avoids pulling full Home Assistant dependencies
- `ukbcd/` -- Lightweight reimplementation of UKBinCollectionData helpers: `AbstractGetBinDataClass`, validators, date functions. Avoids selenium/pandas dependencies
- `requests_fallback.py` -- AsyncClient wrapper using `requests.Session` + `asyncio.to_thread` for Cloudflare-blocked sites
- `curl_cffi_fallback.py` -- AsyncClient wrapper using `curl_cffi` for TLS fingerprint impersonation

**Pipeline** (`pipeline/`):
- `shared.py` -- Common utilities: path constants, blocked domains list, domain normalization, lookup loaders
- `overrides.json` -- Central config for HACS-to-UKBCD fallbacks, curl_cffi backends, SSL overrides, requests fallback scrapers
- `hacs/` -- Scripts to sync and patch hacs_waste_collection_schedule scrapers (AST-based `requests` to async `httpx`)
- `ukbcd/` -- Scripts to sync and patch UKBinCollectionData scrapers (import rewrite, sync httpx, Source adapter generation)
- `upstream/` -- Downloaded originals from both repos (gitignored, populated by sync scripts)
- Each source has a `sync.sh` entry point that clones upstream, patches, and deploys to `api/scrapers/`

**Scripts** (`scripts/`):
- `generate_admin_lookup.py` -- Builds `admin_scraper_lookup.json` from all scrapers
- `lookup/create_lookup_table.py` -- Downloads ONS ONSPD data and builds `postcode_lookup.parquet` and `lad_lookup.json`
- `coverage/generate_coverage_map.py` -- Fetches UK LAD boundaries from ArcGIS and generates `coverage.geojson` and `coverage_map.html`

**Tests** (`tests/`):
- `test_ci.py` -- Smoke tests (about 720): syntax, imports, app boot, registry loading. Runs as pre-commit hook
- `test_frontend.py` -- API surface tests (7): landing page, routes, CORS, error cases
- `test_integration.py` -- Integration tests for requests-based scrapers (about 680): hits live council sites with up to 40 concurrent requests. Uses `test_cases.json` generated from scraper `TEST_CASES`
- `test_playwright.py` -- Integration tests for Playwright-based scrapers (about 44): hits live council sites with up to 10 concurrent requests (lower concurrency because each spawns Chromium). Writes results to `playwright_output.json`
- `test_deploy.py` -- Docker stack tests (3): compose boot, scraper loading, static files
- `conftest.py` -- Custom pytest plugin that writes structured results to `test_output.json` and `integration_output.json`
- Tests use `pytest-asyncio` with `loop_scope="session"` and `asgi-lifespan` for managing the FastAPI app

**Infrastructure**: Docker Compose runs the API + Redis + Caddy (reverse proxy) + Uptime Kuma (monitoring). Pre-commit hooks via lefthook run ruff, biome, hadolint, CI smoke tests, and hacs source sync. Deployment to Hetzner is automated via `deploy/deployment.py`.

## Key Patterns

- Scraper `Source` classes take params like `uprn`, `postcode`, `address` in `__init__` and return `list[Collection]` from `async def fetch()`
- The registry filters params to only those accepted by each scraper's `__init__` signature before invocation
- `admin_scraper_lookup.json` maps council website domains to scraper filenames -- used to auto-detect which scraper to use from a postcode lookup
- The `/calendar/{uprn}` endpoint returns iCal format for calendar subscription
- hacs scrapers take priority over ukbcd; `pipeline/overrides.json` maps specific failing hacs scrapers to working ukbcd alternatives
- Some scrapers use `requests_fallback.py` (Cloudflare-blocked sites) or `curl_cffi_fallback.py` (TLS fingerprinting) instead of plain httpx
