# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

UK Bin Collection API — a FastAPI service that scrapes UK council websites to return bin/waste collection schedules. ~350 council scrapers live in `api/scrapers/`, monkey-patched from two upstream repos (hacs_waste_collection_schedule and UKBinCollectionData) to work as async API endpoints.

## Commands

```bash
# Run dev server
uv run uvicorn api.main:app --reload

# Run all tests (frontend + scraper integration)
uv run pytest tests/ -v

# Run only frontend/API tests (fast, no external calls)
uv run pytest tests/test_frontend.py -v

# Run scraper integration tests (hits live council sites, slow)
uv run pytest tests/test_api_scrapers.py -v

# Run a single scraper test by keyword
uv run pytest tests/test_api_scrapers.py -v -k "aberdeen"

# Lint Python (ruff — excludes api/scrapers/)
uv run ruff check --fix

# Lint JS/JSON (biome)
npx @biomejs/biome check --write

# Sync and patch scrapers from upstream repos
pipeline/hacs/sync.sh      # hacs_waste_collection_schedule (primary)
pipeline/ukbcd/sync.sh     # UKBinCollectionData (fallback)

# Regenerate test_cases.json from scraper TEST_CASES
uv run python -m pipeline.hacs.generate_test_lookup

# Regenerate admin_scraper_lookup.json (council domain → scraper ID mapping)
uv run python -m pipeline.hacs.generate_admin_lookup

# Docker
docker compose up --build
```

## Architecture

**API layer** (`api/`):
- `main.py` — FastAPI app with lifespan managing `ScraperRegistry`, `AddressLookup`, and optional Redis
- `routes.py` — All endpoints: `/api/v1/addresses/{postcode}`, `/api/v1/council/{postcode}`, `/api/v1/lookup/{uprn}`, `/api/v1/calendar/{uprn}`, `/api/v1/councils`, `/api/v1/health`. Routes are mounted under both `/api` and `/api/v1`
- `services/scraper_registry.py` — Dynamically imports all `api/scrapers/*.py` at startup, introspects `Source.__init__` signatures for required/optional params, and dispatches `await source.fetch()` calls
- `services/address_lookup.py` — Resolves postcodes to addresses (via Mid Suffolk API) and to local authorities (via gov.uk API)
- `services/models.py` — Pydantic response models
- `services/rate_limiting.py` — Redis-backed rate limiter (disabled when no `REDIS_URL`)
- `data/admin_scraper_lookup.json` — Council domain → scraper ID mapping

**Scrapers** (`api/scrapers/`):
- ~350 files (flat directory), one per council. Each defines `TITLE`, `URL`, `TEST_CASES`, and a `Source` class with `async def fetch() -> list[Collection]`
- ~240 from hacs (named `*_gov_uk.py`), ~110 from ukbcd (named `robbrad_*.py`)
- Excluded from ruff linting (configured in `pyproject.toml`)

**Compat shims** (`api/compat/`):
- `hacs/` — Minimal types/helpers synced from hacs upstream: `Collection`, `CollectionBase`, `CollectionGroup`, `ICS`, `SSLError`. Avoids pulling full Home Assistant dependencies
- `ukbcd/` — Lightweight reimplementation of UKBinCollectionData helpers: `AbstractGetBinDataClass`, validators, date functions. Avoids selenium/pandas dependencies

**Pipeline** (`pipeline/`):
- `hacs/` — Scripts to sync and patch hacs_waste_collection_schedule scrapers (AST-based `requests` → async `httpx`)
- `ukbcd/` — Scripts to sync and patch UKBinCollectionData scrapers (import rewrite, sync httpx, Source adapter generation)
- `upstream/` — Downloaded originals from both repos (gitignored, populated by sync scripts)
- Each source has a `sync.sh` entry point that clones upstream, patches, and deploys to `api/scrapers/`

**Scripts** (`scripts/`):
- `lookup/` — Address lookup utilities
- `generate_coverage_map.py` — Coverage map generation

**Tests** (`tests/`):
- `test_frontend.py` — Fast unit tests for app startup, pages, CORS, error cases
- `test_api_scrapers.py` — Integration tests that hit live council sites concurrently (20 max). Uses `test_cases.json` generated from scraper `TEST_CASES`
- `conftest.py` — Custom pytest plugin that writes structured results to `test_output.json`
- Tests use `pytest-asyncio` with `loop_scope="session"` and `asgi-lifespan` for managing the FastAPI app

**Infrastructure**: Docker Compose runs the API + Redis + Caddy (reverse proxy) + Uptime Kuma (monitoring). Pre-commit hooks via lefthook run ruff, biome, hadolint, caddy validate, and `.gov.uk` source sync.

## Key Patterns

- Scraper `Source` classes take params like `uprn`, `postcode`, `address` in `__init__` and return `list[Collection]` from `async def fetch()`
- The registry filters params to only those accepted by each scraper's `__init__` signature before invocation
- `admin_scraper_lookup.json` maps council website domains to scraper filenames — used to auto-detect which scraper to use from a postcode lookup
- The `/calendar/{uprn}` endpoint returns iCal format for calendar subscription
- hacs scrapers take priority over ukbcd (left merge in lookup generation)
