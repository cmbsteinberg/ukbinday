# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

UK Bin Collection API -- a FastAPI service that scrapes UK council websites to return bin/waste collection schedules. About 310 council scrapers live in `api/scrapers/`, patched from two upstream repos (hacs_waste_collection_schedule and UKBinCollectionData) to work as async API endpoints.

## Commands

```bash
# Run dev server
uv run uvicorn api.main:app --reload

# Run tests by marker
uv run pytest -m ci -v                    # smoke tests (syntax, imports, registry)
uv run pytest -m api -v                   # API routes, CORS, error cases
uv run pytest -m live -v                  # hits live council sites, slow
uv run pytest -m docker -v                # Docker compose stack
uv run pytest -m "not live and not docker" -v  # all fast tests

# Run a single scraper test by keyword
uv run pytest tests/test_integration.py -v -k "aberdeen"

# Lint Python (ruff -- excludes api/scrapers/)
uv run ruff check --fix

# Lint JS/JSON (biome)
npx @biomejs/biome check --write

# Sync and patch all scrapers from upstream repos
pipeline/sync.sh                     # orchestrates both HACS + UKBCD
pipeline/hacs/sync.sh                # hacs_waste_collection_schedule only
pipeline/ukbcd/sync.sh               # UKBinCollectionData only

# Regenerate test_cases.json from scraper TEST_CASES
uv run python -m pipeline.hacs.generate_test_lookup   # hacs scrapers
uv run python -m pipeline.ukbcd.generate_test_lookup   # ukbcd scrapers (merges into same file)

# Regenerate admin_scraper_lookup.json (council domain to scraper ID mapping)
uv run python -m scripts.generate_admin_lookup

# Regenerate postcode/LAD lookup data
uv run python -m scripts.lookup.create_lookup_table

# Regenerate coverage map
uv run python -m scripts.coverage.generate_coverage_map

# Regenerate README sankey diagram from lad_lookup.json + tests/output/integration_output.json
uv run python -m scripts.generate_sankey

# Annotate lad_lookup.json with working/broken status from test results
uv run python -m scripts.annotate_lad_working

# Run all post-integration regeneration scripts (coverage map, sankey, lad annotations)
./pipeline/ci/post_integration.sh

# Docker
docker compose up --build
```

## Architecture

**API layer** (`api/`):
- `main.py` -- FastAPI app with lifespan managing `ScraperRegistry`, `CouncilLookup`, optional Redis, and `BrowserPool`
- `config.py` -- Centralised configuration from environment variables (timeouts, rate limits, address API, CORS, logging)
- `routes.py` -- All endpoints: `/api/v1/addresses/{postcode}`, `/api/v1/council/{postcode}`, `/api/v1/lookup/{uprn}`, `/api/v1/calendar/{uprn}`, `/api/v1/councils`, `/api/v1/health`, `/api/v1/status`, `/api/v1/metrics`, `/api/v1/report`. Routes are mounted under `/api/v1` only
- `services/scraper_registry.py` -- Dynamically imports all `api/scrapers/*.py` at startup, introspects `Source.__init__` signatures for required/optional params, and dispatches `await source.fetch()` calls
- `services/council_lookup.py` -- Resolves postcodes to local authorities via local parquet lookup with ibis/duckdb. Provides `CouncilLookup` class with `get_local_authority()` and `get_authority_by_slug()`
- `services/address_lookup.py` -- Resolves postcodes to addresses via external address API (configured via `ADDRESS_API_URL` and `ADDRESS_API_COMPANY_ID`)
- `services/models.py` -- Pydantic response models
- `services/rate_limiting.py` -- Redis-backed rate limiter (disabled when no `REDIS_URL`)
- `services/ics_cache.py` -- Persistent on-disk ICS cache keyed by UPRN. Writes `data/calendars/{uprn}.ics` + `{uprn}.json` sidecar atomically. The ICS file is the source of truth served by `/calendar`; the sidecar holds scraper params, `last_success`, `consecutive_failures`, and an upcoming-collections slice for `/lookup`
- `services/refresh_job.py` -- Nightly worker that re-scrapes stale UPRNs. Scans sidecars, skips UPRNs successfully refreshed within `ICS_REFRESH_MIN_AGE_HOURS`, fans out via bounded queue, deletes entries after `ICS_FAILURE_THRESHOLD` consecutive failures. Runs in a dedicated `worker` container (API sets `RUN_REFRESH_JOB=0`)
- `services/scrape_lock.py` -- Redis `SET NX` lock keyed by UPRN, shared by API and worker so the same UPRN isn't scraped twice concurrently
- `data/admin_scraper_lookup.json` -- Council domain to scraper ID mapping
- `data/lad_lookup.json` -- LAD code to council name, URL, scraper ID, and working status
- `badge_coverage.json` (repo root) -- Coverage stats for README badge
- `data/postcode_lookup.parquet` -- 1.6M postcodes mapped to LAD codes for fast local lookup
- `data/calendars/` -- On-disk ICS cache (`{uprn}.ics` + `{uprn}.json` sidecar), gitignored
- `templates/` -- HTML pages: landing (`index.html`), coverage map (`coverage.html`), API docs (`api-docs.html`)
- `static/` -- Frontend JS (`app.js`), coverage GeoJSON, Leaflet map

**Scrapers** (`api/scrapers/`):
- About 310 files (flat directory), one per council. Each defines `TITLE`, `URL`, `TEST_CASES`, and a `Source` class with `async def fetch() -> list[Collection]`
- About 235 from hacs (named `hacs_*_gov_uk.py`), about 73 from ukbcd (named `ukbcd_*.py`)
- Excluded from ruff linting (configured in `pyproject.toml`)

**Compat shims** (`api/compat/`):
- `hacs/` -- Minimal types/helpers synced from hacs upstream: `Collection`, `CollectionBase`, `CollectionGroup`, `ICS`, `SSLError`. Avoids pulling full Home Assistant dependencies
- `ukbcd/` -- Lightweight reimplementation of UKBinCollectionData helpers: `AbstractGetBinDataClass`, validators, date functions. Avoids selenium/pandas dependencies
- `requests_fallback.py` -- AsyncClient wrapper using `requests.Session` + `asyncio.to_thread` for Cloudflare-blocked sites
- `curl_cffi_fallback.py` -- AsyncClient wrapper using `curl_cffi` for TLS fingerprint impersonation
- `httpx_helpers.py` -- Helpers for one-shot httpx requests that properly close the client

**Pipeline** (`pipeline/`):
- `sync.sh` -- Top-level sync orchestrator: runs `sync_all.py` which fetches input.json (source of truth for needed councils), syncs HACS scrapers, fills gaps with UKBCD, and regenerates lookups
- `shared.py` -- Common utilities: path constants, blocked domains list, domain normalization, lookup loaders
- `overrides.json` -- Central config for HACS-to-UKBCD fallbacks, curl_cffi backends, SSL overrides, requests fallback scrapers
- `hacs/` -- Scripts to sync and patch hacs_waste_collection_schedule scrapers (AST-based `requests` to async `httpx`)
- `ukbcd/` -- Scripts to sync and patch UKBinCollectionData scrapers (import rewrite, sync httpx, Source adapter generation)
- `upstream/` -- Downloaded originals from both repos (gitignored, populated by sync scripts)

**Scripts** (`scripts/`):
- `generate_admin_lookup.py` -- Builds `admin_scraper_lookup.json` from all scrapers
- `generate_sankey.py` -- Generates Mermaid sankey diagram in README.md from `lad_lookup.json` and `tests/output/integration_output.json`
- `annotate_lad_working.py` -- Annotates `lad_lookup.json` with working/broken status based on integration test results
- `pipeline/ci/post_integration.sh` -- Runs all post-integration regeneration scripts (coverage map, sankey, lad annotations)
- `lookup/create_lookup_table.py` -- Downloads ONS ONSPD data and builds `postcode_lookup.parquet` and `lad_lookup.json`
- `coverage/generate_coverage_map.py` -- Fetches UK LAD boundaries from ArcGIS and generates `coverage.geojson` and `coverage_map.html`

**Tests** (`tests/`):
- `test_ci.py` (marker: `ci`) -- Smoke tests (9 test functions, parametrized over ~310 scrapers): syntax, imports, app boot, registry loading. Runs as pre-commit hook
- `test_frontend.py` (marker: `api`) -- API surface tests (8): landing page, routes, CORS, error cases
- `test_integration.py` (marker: `live`) -- Integration tests for requests-based scrapers: hits live council sites with up to 40 concurrent requests. Uses `test_cases.json` generated from scraper `TEST_CASES`
- `test_frontend_flow.py` (marker: `live`) -- End-to-end frontend flow tests: mimics the real user journey (postcode → address pick → lookup)
- `test_deploy.py` (marker: `docker`) -- Docker stack tests (3): compose boot, scraper loading, static files
- `test_deploy_docker.sh` -- Bash-based Docker deployment test (curl assertions, standalone)
- `conftest.py` -- Custom pytest plugin that writes structured results to `output/test_output.json` and `output/integration_output.json`
- `output/` -- Generated test result JSON files (test_output, integration_output, frontend_flow_output)
- `battletest/` -- Ad-hoc shell scripts for load testing, chaos testing, and security checks
- Tests use `pytest-asyncio` with `loop_scope="session"` and `asgi-lifespan` for managing the FastAPI app
- Pytest markers registered in `pyproject.toml`: `ci`, `api`, `live`, `docker`

**CI/CD** (`.github/workflows/deploy.yml`):
- On push to `main`: runs smoke tests → deploys to Hetzner via SSH (git pull + docker compose) → runs integration tests (non-blocking) → regenerates coverage badge and sankey diagram → auto-commits results

**Infrastructure**: Docker Compose runs the API + refresh worker + Redis + Caddy (reverse proxy) + GoAccess (log analytics) + Uptime Kuma (monitoring). API and worker share a named volume (`bins_data`) mounted at `/app/data` for the ICS cache. Pre-commit hooks via lefthook run the unified sync script, ruff, biome, and CI smoke tests. Deployment to Hetzner is automated via GitHub Actions and `deploy/deployment.py`.

## Key Patterns

- Scraper `Source` classes take params like `uprn`, `postcode`, `address` in `__init__` and return `list[Collection]` from `async def fetch()`
- The registry filters params to only those accepted by each scraper's `__init__` signature before invocation
- `admin_scraper_lookup.json` maps council website domains to scraper filenames -- used to auto-detect which scraper to use from a postcode lookup
- The `/calendar/{uprn}` endpoint returns iCal format for calendar subscription
- hacs scrapers take priority over ukbcd; `pipeline/overrides.json` maps specific failing hacs scrapers to working ukbcd alternatives
- Some scrapers use `requests_fallback.py` (Cloudflare-blocked sites) or `curl_cffi_fallback.py` (TLS fingerprinting) instead of plain httpx
- Cache miss on `/lookup` or `/calendar` triggers an inline scrape guarded by the Redis scrape-lock; parallel requests for the same UPRN poll the cache up to `SCRAPE_LOCK_MAX_WAIT_S` (default 15s) and return 503 on timeout rather than racing
- `/calendar/{uprn}` streams the on-disk ICS directly; events are merged on write (stable UIDs = sha1(uprn|date|type)) and pruned by `ICS_RETENTION_DAYS`
- Routes include `/status` (system health with uptime/scraper counts) and `/metrics` (Prometheus-format metrics plus ICS cache entry count and last refresh stats)
