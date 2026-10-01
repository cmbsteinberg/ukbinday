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
uv run pytest -m live -v                  # every council against live sites (~7 min)
uv run pytest -m docker -v                # Docker compose stack
uv run pytest -m "not live and not docker" -v  # all fast tests

# Run the live test for specific councils (LAD codes); a subset run merges into the output file
LAD_CODES=S12000033,E08000035 uv run pytest tests/test_lad_integration.py -v

# Refresh tests/lad_test_cases.json (monthly). Sticky by default: keeps sampled
# addresses unless their last outcome was input_rejected/empty; new or rewired
# LADs get fresh samples. Needs the address API (network).
uv run python -m pipeline.shared.generate_lad_test_cases
uv run python -m pipeline.shared.generate_lad_test_cases --resample-all   # full resample

# Lint Python (ruff -- excludes api/scrapers/)
uv run ruff check --fix

# Lint JS/JSON (biome)
npx @biomejs/biome check --write

# Sync and patch all scrapers from upstream repos (manual only; never a commit hook,
# since it rewrites api/scrapers/ and the generated JSONs)
uv run lefthook run sync             # same as pipeline/sync.sh
pipeline/sync.sh                     # orchestrates both HACS + UKBCD
pipeline/hacs/sync.sh                # hacs_waste_collection_schedule only
pipeline/ukbcd/sync.sh               # UKBinCollectionData only

# Regenerate test_cases.json (upstream fixtures, input to generate_lad_test_cases) from scraper TEST_CASES
uv run python -m pipeline.hacs.generate_test_lookup   # hacs scrapers
uv run python -m pipeline.ukbcd.generate_test_lookup   # ukbcd scrapers (merges into same file)

# Regenerate admin_scraper_lookup.json (council domain to scraper ID mapping)
uv run python -m scripts.generate_admin_lookup

# Publish the committed ONSPD parquet to api/data/postcode_lookup.parquet
uv run python -m scripts.lookup.create_lookup_table

# Check for new ONS/GOV.UK editions (downloads nothing); drop --check to fetch
./scripts/lookup/fetch_latest.sh --check

# Rebuild the council mapping: lad_base.json from upstream, then lad_lookup.json
uv run python -m scripts.lookup.build_lad_lookup
uv run python -m scripts.lookup.build_lad_lookup --compose  # committed files only

# Regenerate coverage map
uv run python -m scripts.coverage.generate_coverage_map

# Annotate lad_lookup.json `working` flags from tests/output/lad_integration_output.json
uv run python -m scripts.annotate_lad_working

# Regenerate README sankey + badge from the `working` flags (run annotate first)
uv run python -m scripts.generate_sankey

# After a live run: annotate, then coverage map, then sankey/badge. Tests never run this.
./pipeline/ci/post_integration.sh

# New scraper contract (api/councils/): run modules on their cases, vs the old scraper
uv run python -m scripts.councils.check hartlepool --compare -v
uv run python -m scripts.councils.check --all --compare --json /tmp/check.json
uv run python -m scripts.councils.convert --plan      # old scraper id -> module name + LADs
uv run ty check                                       # type-checks api/councils/ (pre-commit: staged files only)

# Docker
docker compose up --build
```

## Architecture

**API layer** (`api/`):
- `main.py` -- FastAPI app with lifespan managing `ScraperRegistry`, `CouncilLookup`, and optional Redis
- `config.py` -- Centralised configuration from environment variables (timeouts, rate limits, address API, CORS, logging)
- `routes.py` -- All endpoints: `/api/v1/addresses/{postcode}`, `/api/v1/council/{postcode}`, `/api/v1/lookup/{uprn}`, `/api/v1/calendar/{uprn}`, `/api/v1/councils`, `/api/v1/health`, `/api/v1/status`, `/api/v1/metrics`. Routes are mounted under `/api/v1` only
- `services/scraper_registry.py` -- Dynamically imports all `api/scrapers/*.py` at startup, introspects `Source.__init__` signatures for required/optional params, and dispatches `await source.fetch()` calls
- `services/council_lookup.py` -- Resolves postcodes to local authorities via local parquet lookup with ibis/duckdb. Provides `CouncilLookup` class with `get_local_authority()` and `get_authority_by_slug()`
- `services/address_lookup.py` -- Resolves postcodes to addresses via external address API (configured via `ADDRESS_API_URL` and `ADDRESS_API_COMPANY_ID`)
- `services/models.py` -- Pydantic response models
- `services/rate_limiting.py` -- Redis-backed rate limiter (disabled when no `REDIS_URL`)
- `services/ics_cache.py` -- Persistent on-disk ICS cache keyed by UPRN. Writes `data/calendars/{uprn}.ics` + `{uprn}.json` sidecar atomically. The ICS file is the source of truth served by `/calendar`; the sidecar holds scraper params, `last_success`, `consecutive_failures`, and an upcoming-collections slice for `/lookup`
- `services/refresh_job.py` -- Nightly worker that re-scrapes stale UPRNs. Scans sidecars, skips UPRNs successfully refreshed within `ICS_REFRESH_MIN_AGE_HOURS`, fans out via bounded queue, deletes entries after `ICS_FAILURE_THRESHOLD` consecutive failures. Runs in a dedicated `worker` container (API sets `RUN_REFRESH_JOB=0`)
- `services/scrape_lock.py` -- Redis `SET NX` lock keyed by UPRN, shared by API and worker so the same UPRN isn't scraped twice concurrently
- `data/admin_scraper_lookup.json` -- Council domain to scraper ID mapping
- `data/lad_lookup.json` -- LAD code to council name, scraper URL, scraper ID, GOV.UK waste-service URL, and working status. Generated -- never edit by hand. Keys are exactly the LAD codes `postcode_lookup.parquet` can return (361), so every council a postcode resolves to has an entry even when no scraper exists yet
- `badge_coverage.json` (repo root) -- Coverage stats for README badge
- `data/postcode_lookup.parquet` -- 1.6M postcodes mapped to LAD codes for fast local lookup
- `data/calendars/` -- On-disk ICS cache (`{uprn}.ics` + `{uprn}.json` sidecar), gitignored
- `templates/` -- HTML pages: landing (`index.html`), coverage map (`coverage.html`), API docs (`api-docs.html`)
- `static/` -- Frontend JS (`app.js`), coverage GeoJSON, Leaflet map

**Scrapers** (`api/scrapers/`):
- About 310 files (flat directory), one per council. Each defines `TITLE`, `URL`, `TEST_CASES`, and a `Source` class with `async def fetch() -> list[Collection]`
- About 235 from hacs (named `hacs_*_gov_uk.py`), about 73 from ukbcd (named `ukbcd_*.py`)
- Excluded from ruff linting (configured in `pyproject.toml`)

**Councils, new contract** (`api/councils/`, design in `scraper_contract.md`; migration in progress, not yet wired into the registry):
- `_base/` -- the framework: `Scraper` (stateless; `meta`, `requires`, `headers`, `transport`, `verify_tls`, `icons`, `async fetch(address, http)`), `Meta` (title, url, LAD codes, cases), `Address` (built once from query params; `need()` for required fields), `Http`/`Response` (harness-owned httpx or curl_cffi session; 4xx/5xx and transport failures raise `UpstreamError` unless `check=False`), `Collection` (frozen dataclass: date, type, icon), errors (`InputError`, `AddressNotFound`, `UpstreamError`, `NeedsBrowser`), `match_address`, `parse_date`, `soup`/`text_of`, `parse_ics`, and `run()` which builds the address, checks `requires`, opens `Http`, fetches and tidies (dedupe, sort, icons)
- `_platforms/` -- shared council platforms (Whitespace, ...) as `Scraper` subclasses configured per council
- `<council>.py` -- one module per scraper, named after its LADs, exposing `SCRAPER`. Stricter lint via `api/councils/ruff.toml` (ASYNC, BLE, B)

**Compat shims** (`api/compat/`):
- `hacs/` -- Minimal types/helpers synced from hacs upstream: `Collection`, `CollectionBase`, `CollectionGroup`, `ICS`, `SSLError`. Avoids pulling full Home Assistant dependencies
- `ukbcd/` -- Lightweight reimplementation of UKBinCollectionData helpers: `AbstractGetBinDataClass`, validators, date functions. Avoids selenium/pandas dependencies
- `requests_fallback.py` -- AsyncClient wrapper using `requests.Session` + `asyncio.to_thread` for Cloudflare-blocked sites
- `curl_cffi_fallback.py` -- AsyncClient wrapper using `curl_cffi` for TLS fingerprint impersonation
- `httpx_helpers.py` -- Helpers for one-shot httpx requests that properly close the client

**Pipeline** (`pipeline/`):
- `sync.sh` -- Top-level sync orchestrator: runs `sync_all.py` which fetches input.json (source of truth for which councils have a *scraper*, not for which councils exist), syncs HACS scrapers, fills gaps with UKBCD, and regenerates lookups
- `data/lad_base.json` -- Ground-truth LAD code to `{name, govuk_url}` for all 361 councils, from ONS + GOV.UK. Only changes when upstream does (`scripts/lookup/fetch_latest.sh`)
- `data/scraper_lad_map.json` -- LAD code to `{scraper_id, url}`, written by `ukbcd/patch_scrapers.py` and patched by `sync_all._merge_preserved_scrapers`. Composed with `lad_base.json` into `api/data/lad_lookup.json`
- `data/onspd_postcode_lad.parquet`, `data/onsud_uprn_postcode.parquet` -- Committed ONS extracts (15MB/88MB) so a checkout, test run or deploy never needs the multi-hundred-MB upstream zips
- `shared.py` -- Common utilities: path constants, blocked domains list, domain normalization, lookup loaders
- `overrides.json` -- Central config for HACS-to-UKBCD fallbacks, curl_cffi backends, SSL overrides, requests fallback scrapers
- `lad_overrides.json` -- `scraper_id` to LAD codes, applied after the sync's own wiring wins. Needed wherever input.json can't wire a scraper itself: the council's listed URL is a third-party portal (`mybasildon.powerappsportals.com`) or plain wrong (Teignbridge's is `google.co.uk`), its `LAD24CD` is wrong (Gosport's said `E07000082`, which is Stroud), or the code was recoded (East Herts `E07000097` to `E07000242`). `build_lad_lookup.check_scraper_matches_council` warns when a LAD's scraper matches neither the council name nor its GOV.UK domain, which is how the next such case gets caught
- `hacs/` -- Scripts to sync and patch hacs_waste_collection_schedule scrapers (AST-based `requests` to async `httpx`)
- `ukbcd/` -- Scripts to sync and patch UKBinCollectionData scrapers (import rewrite, sync httpx, Source adapter generation)
- `upstream/` -- Downloaded originals from both repos (gitignored, populated by sync scripts)

**Scripts** (`scripts/`):
- `generate_admin_lookup.py` -- Builds `admin_scraper_lookup.json` from all scrapers
- `lad_status.py` -- The one definition of a council's status, used by the live test and every consumer. `working`: a *sampled* case passed (200 + at least one collection); for `fixture_only` LADs (scraper requires params `/addresses` can't supply, e.g. property_id, usrn) a fixture pass counts instead. A fixture pass with all sampled cases failing is `broken`. `unverified` (every deciding case unreachable, or none) keeps the previous flag
- `annotate_lad_working.py` -- Writes `working` into `lad_lookup.json` from `tests/output/lad_integration_output.json` via `lad_status.py`
- `generate_sankey.py` -- Generates the Mermaid sankey in README.md and `badge_coverage.json` from the `working` flags in `lad_lookup.json`
- `pipeline/ci/post_integration.sh` -- Explicit post-run step: annotate, then coverage map, then sankey/badge. No test calls it
- `lookup/fetch_latest.sh` -- Version-checked fetch of the four upstream sources (ONSPD, ONSUD, ONS LAD boundaries, GOV.UK Local Links Manager) into `$BINS_DATA_CACHE` (default `~/.cache/bins-data`). ONSPD/ONSUD are ArcGIS items that mint a new id per edition and ignore conditional GETs, so freshness comes from the item's `modified` stamp in `.upstream_version`, not `curl -z`; the small sources do use ETag/`If-Modified-Since`. `--check` reports staleness without downloading, `--small-only` skips the multi-hundred-MB zips
- `lookup/create_lookup_table.py` -- Publishes the committed ONSPD parquet to `postcode_lookup.parquet`. `--from-onspd`/`--from-onsud` rebuild the pipeline parquets from an unpacked ONS release and stamp the edition into parquet key-value metadata (`SELECT * FROM parquet_kv_metadata(...)`); `--stamp-edition` labels an existing parquet in place
- `lookup/build_lad_lookup.py` -- Rebuilds the council mapping from ground truth. Stage 1 joins ONS boundary names and GOV.UK waste URLs onto the distinct LAD codes in `onspd_postcode_lad.parquet` and writes `pipeline/data/lad_base.json`; stage 2 (`--compose`) merges that with `pipeline/data/scraper_lad_map.json` into `api/data/lad_lookup.json`. Where sources disagree on a code after a reorganisation (ONS boundaries lead ONSPD on `E08000038/39` vs `E08000016/19`; GOV.UK lags on the 2023 unitaries), `CODE_ALIASES` re-keys the row onto the code ONSPD actually returns -- an unnamed code is a hard error, not a null name
- `coverage/generate_coverage_map.py` -- Fetches UK LAD boundaries from ArcGIS and generates `coverage.geojson`; status from the `working` flag, `pass_rate` from the last live run

**Tests** (`tests/`):
- `test_ci.py` (marker: `ci`) -- Smoke tests (9 test functions, parametrized over ~310 scrapers): syntax, imports, app boot, registry loading. Runs as pre-commit hook
- `test_frontend.py` (marker: `api`) -- API surface tests (8): landing page, routes, CORS, error cases
- `test_scrape_cache.py` (marker: `api`) -- ICS cache keying with stubbed scrapers: `/lookup/0` never caches, a cache entry never answers for a different scraper, `/calendar/0` is rejected
- `test_deeplinks.py` (marker: `api`), `test_sync_pipeline.py` (marker: `ci`) -- deeplink routing and sync pipeline checks
- `test_lad_integration.py` (marker: `live`) -- One test per wired LAD (council), not per scraper. Reads `lad_test_cases.json`, runs each case through the real `/lookup/{uprn}` route in-process with the params the frontend sends, retries failures once at low concurrency, probes scraper hosts to tell `unreachable` (this machine can't reach it) from `upstream_error`. Case outcomes: pass, empty, input_rejected, unreachable, upstream_error, scraper_error. Writes `output/lad_integration_output.json` (subset runs via `LAD_CODES` merge into it); status per LAD from `scripts/lad_status.py`. ~7 min for all 350 LADs
- `lad_test_cases.json` -- Generated by `pipeline/shared/generate_lad_test_cases.py`, keyed by LAD code: `{name, scraper_id, fixture_only?, cases: [{id, source: sampled|fixture, label, params}]}`. Sampled cases: an ONSUD postcode in the LAD (4-60 UPRNs), resolved through the address API, keeping a plain-numbered address whose UPRN is in ONSUD. Fixture cases come from `test_cases.json` (upstream `TEST_CASES`, built by the hacs/ukbcd `generate_test_lookup` scripts)
- `test_deploy.py` (marker: `docker`) -- Docker stack tests (3): compose boot, scraper loading, static files
- `test_deploy_docker.sh` -- Bash-based Docker deployment test (curl assertions, standalone)
- `conftest.py` -- Test-time env defaults (fresh `DATA_DIR` tempdir per session, address API config)
- `output/lad_integration_output.json` -- Last live run, committed; input to `post_integration.sh` and to the sticky test-case refresh
- `battletest/` -- Ad-hoc shell scripts for load testing, chaos testing, and security checks
- Tests use `pytest-asyncio` with `loop_scope="session"` and `asgi-lifespan` for managing the FastAPI app
- Pytest markers registered in `pyproject.toml`: `ci`, `api`, `live`, `docker`

**CI/CD** (`.github/workflows/deploy.yml`):
- On push to `main`: runs `tests/test_ci.py` only → deploys to Hetzner via SSH (git pull + docker compose). Live tests do not run in CI; run `tests/test_lad_integration.py` then `./pipeline/ci/post_integration.sh` locally and commit the output, flags, badge and sankey

**Infrastructure**: Docker Compose runs the API + refresh worker + Redis + Caddy (reverse proxy) + GoAccess (log analytics) + Uptime Kuma (monitoring). API and worker share a named volume (`bins_data`) mounted at `/app/data` for the ICS cache. Pre-commit hooks via lefthook run ruff, biome, and CI smoke tests; the upstream sync is a manual `lefthook run sync`. Deployment to Hetzner is automated via GitHub Actions and `deploy/deployment.py`.

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
