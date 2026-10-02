# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

UK Bin Collection API -- a FastAPI service that scrapes UK council websites to return bin/waste collection schedules. Each council is a module in `api/councils/` (design in `scraper_contract.md`). The modules began as ports of two upstream repos (hacs_waste_collection_schedule and UKBinCollectionData) and are maintained here; `scripts/upstream_watch.sh` flags upstream fixes to councils we serve. The retired sync that produced the original ports is described in `upstream_sync.md` and preserved at the git tag `upstream-sync-final`.

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

# Lint Python
uv run ruff check --fix

# Lint JS/JSON (biome)
npx @biomejs/biome check --write

# Upstream commits touching councils we serve, since the last check (pre-commit runs it daily with --hook)
scripts/upstream_watch.sh
scripts/upstream_watch.sh --since 2026-09-01

# Publish the committed ONSPD parquet to api/data/postcode_lookup.parquet
uv run python -m scripts.lookup.create_lookup_table

# Check for new ONS/GOV.UK editions (downloads nothing); drop --check to fetch
./scripts/lookup/fetch_latest.sh --check

# Refresh the committed gov.uk bank holidays snapshot (api/data/bank_holidays.json; v2 `holiday`)
uv run python -m scripts.lookup.fetch_bank_holidays

# Rebuild the council mapping: lad_base.json from upstream, then lad_lookup.json
uv run python -m scripts.lookup.build_lad_lookup
uv run python -m scripts.lookup.build_lad_lookup --compose  # committed files only; run after adding a module or changing its lads/url

# Regenerate coverage map
uv run python -m scripts.coverage.generate_coverage_map

# Annotate lad_lookup.json `working` flags from tests/output/lad_integration_output.json
uv run python -m scripts.annotate_lad_working

# Regenerate README sankey + badge from the `working` flags (run annotate first)
uv run python -m scripts.generate_sankey

# After a live run: annotate, then coverage map, then sankey/badge. Tests never run this.
./pipeline/ci/post_integration.sh

# Run council modules on their fixtures and sampled addresses (live sites)
uv run python -m scripts.councils.check hartlepool -v
uv run python -m scripts.councils.check --all --json /tmp/check.json
uv run ty check                                       # type-checks api/councils/ (pre-commit: staged files only)

# Docker
docker compose up --build
```

## Architecture

**API layer** (`api/`):
- `main.py` -- FastAPI app with lifespan managing `ScraperRegistry`, `CouncilLookup`, and optional Redis
- `config.py` -- Centralised configuration from environment variables (timeouts, rate limits, address API, CORS, logging)
- `routes/` -- Every endpoint, mounted under `/api/v2` (OpenAPI at `/api/v2/openapi.json`, `/docs`, `/redoc`). `v2.py`: `/find?postcode=`, `/{lad}/view/{uprn}`, `/{lad}/subscribe/{uprn}`, `/{lad}/download/{uprn}`, shaped after the LocalGov Drupal waste collection module. `find` answers `{postcode, council, council_name, candidates, deeplink, addresses}`: `council` is the LAD code when the registry serves it, with the address list (address API; only this step is behind Turnstile: without an `X-Turnstile-Token` it is null and the council still answers, a failed token is 403); an unwired LAD, or a module with `needs_browser`, answers `council: null` with its `deeplink` and no addresses, without calling the address API. `view` answers `{uprn, council, cached, cached_at, dates: [{date (ISO), holiday, type: {label, colour, icon}}], deeplink}`, with `colour` from `colour_of` and `holiday` from `services/bank_holidays.py`; `subscribe` is the ICS feed (calendar links), `download` the same with a `Content-Disposition`. Deliberate deviations from Drupal: ISO dates, a structured address list, no `weekly_collection`/`collection_time`. The logic is in `schedule.py` (`find`, `get_schedule`, `calendar_response`, `search_addresses`, `turnstile_passed`). `meta.py`: `/councils`, `/health`, `/status`, `/metrics`. `internal.py`: `/internal/refresh?shard=&of=` (hidden from the schema: one refresh pass, for Vercel cron; refused unless `CRON_SECRET` is set and sent as `Authorization: Bearer`). `legacy.py`: the one v1 route kept, `/api/v1/calendar/{uprn}?council=` (hidden), serving the same feed as `subscribe` so pre-v2 calendar subscriptions keep updating
- `services/scraper_registry.py` -- Loads the council modules (`api/councils/*.py`, via `_base/discovery.py`). The public council ID is the ONS LAD code: what `/find` returns, `/councils` lists, calendar URLs carry and ICS sidecars store. A module is registered once per LAD in its `meta.lads` (Adur & Worthing answers to both codes, each with its own GOV.UK deeplink). Wiring is the registry's call, not `lad_lookup.json`'s: `/find` returns the LAD code when the registry serves it, else the LAD's deeplink. Every old scraper ID in `api/councils/_aliases.json` resolves to its LAD (`get()`, `canonical_id()`), and `/{lad}/view` answers with the LAD code; an old ID with no alias (a scraper retired without a module) answers to nothing. `/councils` params come from `requires` (`label` is sent as `address`). `invoke()` runs `api.councils._base.run(scraper, params)` under `SCRAPER_TIMEOUT`; an unknown ID raises `UnknownCouncilError`
- `services/scrape_orchestrator.py` -- Cache-or-scrape with the scrape lock, and `map_scrape_exception`: `InputError`/`AddressNotFound` 422 (AddressNotFound's `suggestions` go in the body), `UpstreamError`/`httpx.HTTPError` 503, timeout 504, anything else 503 (a bug). `NeedsBrowser` answers with a deeplink (module `meta.url`, else GOV.UK); `subscribe`/`download` answer 404 with the reason, since a calendar app can't use a web page. A site failure (`UpstreamError` or timeout) with nothing cached makes `view` answer 200 with a GOV.UK-first deeplink and an `X-Scrape-Failure: network|blocked|timeout` header (`blocked`: the `UpstreamError` carried `BOT_PROTECTION`); `subscribe`/`download` keep the 503/504
- `services/deeplinks.py` -- The "check on the council website" response: unwired LADs (from `lad_lookup.json`), plus `for_needs_browser` and `for_upstream_failure` for wired councils. Every deeplink names its `Blocker` (`blocker` code + `blocker_label`: captcha, login, bot_protection, browser_only, no_lookup, site_down, not_supported): unwired from `lad_overrides.json`, NeedsBrowser from the exception or module, an upstream failure is `bot_protection` when the `UpstreamError` carries it (`Response` detects a bot wall: Cloudflare challenge/403/429, Incapsula), else `site_down`
- `services/council_lookup.py` -- Resolves postcodes to local authorities via local parquet lookup with duckdb. Provides `CouncilLookup.get_local_authority()` (name, homepage URL, LAD code; whether the LAD is wired is the registry's call)
- `services/address_lookup.py` -- Resolves postcodes to addresses via external address API (configured via `ADDRESS_API_URL` and `ADDRESS_API_COMPANY_ID`)
- `services/models.py` -- Pydantic response models
- `services/rate_limiting.py` -- Redis-backed rate limiter (disabled when no `REDIS_URL`)
- `services/blob_store.py` -- `get`/`put`/`delete`/`keys` store under the ICS cache: `R2BlobStore` (Cloudflare R2 via boto3) when `R2_BUCKET` is set, else `LocalBlobStore` at `DATA_DIR`
- `services/ics_cache.py` -- Persistent ICS cache keyed by UPRN, on a blob store. Writes `calendars/{uprn}.ics` then the `{uprn}.json` sidecar, and the refresh heartbeat `meta/refresh_heartbeat.json` (one record per shard; `/metrics` reports its age). The ICS file is the source of truth served by `subscribe`/`download`; the sidecar holds scraper params, `last_success`, `consecutive_failures`, and an upcoming-collections slice for `view`
- `services/refresh_job.py` -- Nightly worker that re-scrapes stale UPRNs. Scans sidecars, skips UPRNs successfully refreshed within `ICS_REFRESH_MIN_AGE_HOURS`, fans out via bounded queue, deletes entries after `ICS_FAILURE_THRESHOLD` consecutive failures. `run_once(shard, of, deadline)` takes UPRNs with `int(uprn) % of == shard` and stops queueing at the deadline (the rest are `deferred` to the next pass). In production a Vercel cron calls `/api/v2/internal/refresh`; with `RUN_REFRESH_JOB=1` it runs nightly in-process instead (local/Docker)
- `services/scrape_lock.py` -- Redis `SET NX` lock keyed by UPRN, shared by API and worker so the same UPRN isn't scraped twice concurrently
- `services/bank_holidays.py` -- `holiday_name(lad, day)` from the committed gov.uk snapshot `data/bank_holidays.json`; region from the LAD code's first letter (E/W, S, N)
- `data/lad_lookup.json` -- LAD code to council name, `scraper_id` (the name of the module claiming it, null when unwired), `url` (the module's `meta.url`, or a `deeplink_urls` override for an unwired LAD), GOV.UK waste-service URL, unwired `status` note, and working status. `scraper_id` is not a public ID; the tooling keys on it (wired-or-not for coverage/sankey/deeplinks, sticky test-case refresh, `lad_status` rewire detection). Generated by `build_lad_lookup --compose` -- never edit by hand. Keys are exactly the LAD codes `postcode_lookup.parquet` can return (361), so every council a postcode resolves to has an entry even when no scraper exists yet
- `badge_coverage.json` (repo root) -- Coverage stats for README badge
- `data/postcode_lookup.parquet` -- 1.6M postcodes mapped to LAD codes for fast local lookup
- `data/calendars/` -- On-disk ICS cache (`{uprn}.ics` + `{uprn}.json` sidecar), gitignored
- `templates/` -- HTML pages: landing (`index.html`), coverage map (`coverage.html`), API docs (`api-docs.html`)
- `static/` -- Frontend JS (`app.js`), coverage GeoJSON, Leaflet map

**Councils** (`api/councils/`, design in `scraper_contract.md`; the source of truth for which LADs are wired):
- `_base/` -- the framework: `Scraper` (stateless; `meta`, `requires`, `headers`, `transport`, `verify_tls`, `icons`, `async fetch(address, http)`), `Meta` (title, url, LAD codes, cases), `Address` (built once from query params; `need()` for required fields), `Http`/`Response` (harness-owned httpx or curl_cffi session; 4xx/5xx and transport failures raise `UpstreamError` unless `check=False`), `Collection` (frozen dataclass: date, type, icon), errors (`InputError`, `AddressNotFound`, `UpstreamError`, `NeedsBrowser`), `colour_of` (the bin colour a label names, or None; "Green waste" is a stream, not a colour), `match_address`, `parse_date`, `soup`/`text_of`, `parse_ics`, and `run()` which builds the address, checks `requires`, opens `Http`, fetches and tidies (dedupe, sort, icons)
- `_platforms/` -- shared council platforms (Whitespace, ...) as `Scraper` subclasses configured per council
- `<council>.py` -- one module per scraper, named after its LADs, exposing `SCRAPER`. Stricter lint via `api/councils/ruff.toml` (ASYNC, BLE, B). `needs_browser = "<reason>"` makes it a deeplink (Coventry, Havant), including on `/find`; `blocker = Blocker.X` names the wall for it (default `BROWSER_ONLY`)
- `_aliases.json` -- old scraper ID (every one ever wired to a LAD, up to the switch to LAD codes) or recoded LAD code -> current LAD code. Frozen: ICS sidecars carry these IDs, and they still resolve in the `{lad}` path segment. Add an entry only when ONS recodes a LAD; module renames don't need one. `scripts/upstream_watch.sh` also reads it to map each module to its upstream file

**Pipeline** (`pipeline/`):
- `data/lad_base.json` -- Ground-truth LAD code to `{name, govuk_url}` for all 361 councils, from ONS + GOV.UK. Only changes when upstream does (`scripts/lookup/fetch_latest.sh`)
- `data/onspd_postcode_lad.parquet`, `data/onsud_uprn_postcode.parquet` -- Committed ONS extracts (15MB/88MB) so a checkout, test run or deploy never needs the multi-hundred-MB upstream zips
- `shared/__init__.py` -- `normalise_domain` and the loaders for `lad_overrides.json`
- `shared/generate_lad_test_cases.py` -- builds `tests/lad_test_cases.json` (see Tests)
- `lad_overrides.json` -- Notes for councils deliberately left unwired: `unwired_lads` (LAD -> `{blocker, reason}`, shipped as the entry's `blocker` and `status` and shown in the deeplink) and `deeplink_urls` (LAD -> bin page, where the GOV.UK link is dead or wrong). `build_lad_lookup` refuses a LAD that is both listed here and claimed by a module, and `check_scraper_matches_council` warns when a module's `meta.url` matches neither the council name nor its GOV.UK domain (a wrong code in `meta.lads`)

**Scripts** (`scripts/`):
- `upstream_watch.sh` -- Lists new commits in the two upstream repos touching the source file of a council we serve (old IDs in `_aliases.json` name the file: `hacs_<x>` -> `source/<x>.py`, `ukbcd_<x>`/`port_<x>` -> `councils/<CamelCase>.py`). `upstream_watch.json` (gitignored) holds the last check, so each run reports only what's new. `--hook` (lefthook pre-commit) runs at most once a day, caps each `gh` call at 5s and the whole check at ~20s, is silent offline or without `gh`, always exits 0
- `councils/check.py` -- Runs council modules on their `meta.cases` and their LADs' sampled addresses against the live sites
- `lad_status.py` -- The one definition of a council's status, used by the live test and every consumer. `working`: a *sampled* case passed (200 + at least one date); for `fixture_only` LADs (scraper requires params `/find` can't supply, e.g. property_id, usrn) a fixture pass counts instead. A fixture pass with all sampled cases failing is `broken`. `deeplink`: deciding cases answered with a NeedsBrowser deeplink (not working). `unverified` (every deciding case unreachable, or none) keeps the previous flag
- `lad_cases.py` -- Case running shared by the live test and the Vercel probe: loading `lad_test_cases.json`, request path and params from a case, `/{lad}/view` response to case outcome, retry rule
- `vercel_probe.py` -- Runs the deciding cases against a deployed `/api/v2/{lad}/view` (`--base-url`) and diffs per-LAD status against the last live run; exits 1 on regressions (councils that block the host's egress IPs). `--cron-secret` (env `CRON_SECRET`) sends `fresh=1`, a live scrape past the calendar cache (refused without the secret); `--write-output` replaces `tests/output/lad_integration_output.json` with the run, which is how the weekly Coverage workflow makes production the source of the `working` flags
- `annotate_lad_working.py` -- Writes `working` into `lad_lookup.json` from `tests/output/lad_integration_output.json` via `lad_status.py`
- `generate_sankey.py` -- Rewrites README.md's `<!-- coverage:start/end -->` block and `badge_coverage.json` (bin dates / all 361 LADs). Each LAD is bin dates (`working`), deeplink by design (unwired, with its `lad_overrides` status, or a module's `needs_browser`), or broken (with its last live-run status)
- `pipeline/ci/post_integration.sh` -- Explicit post-run step: annotate, then coverage map, then sankey/badge. No test calls it
- `lookup/fetch_latest.sh` -- Version-checked fetch of the four upstream sources (ONSPD, ONSUD, ONS LAD boundaries, GOV.UK Local Links Manager) into `$BINS_DATA_CACHE` (default `~/.cache/bins-data`). ONSPD/ONSUD are ArcGIS items that mint a new id per edition and ignore conditional GETs, so freshness comes from the item's `modified` stamp in `.upstream_version`, not `curl -z`; the small sources do use ETag/`If-Modified-Since`. `--check` reports staleness without downloading, `--small-only` skips the multi-hundred-MB zips
- `lookup/create_lookup_table.py` -- Publishes the committed ONSPD parquet to `postcode_lookup.parquet`. `--from-onspd`/`--from-onsud` rebuild the pipeline parquets from an unpacked ONS release and stamp the edition into parquet key-value metadata (`SELECT * FROM parquet_kv_metadata(...)`); `--stamp-edition` labels an existing parquet in place
- `lookup/build_lad_lookup.py` -- Rebuilds the council mapping from ground truth. Stage 1 joins ONS boundary names and GOV.UK waste URLs onto the distinct LAD codes in `onspd_postcode_lad.parquet` and writes `pipeline/data/lad_base.json`; stage 2 (`--compose`) merges that with each module's `meta.lads`/`meta.url` and the unwired notes in `pipeline/lad_overrides.json` into `api/data/lad_lookup.json`, carrying `working` across only for the same module (an old ID counts as the module its alias resolves to). Where sources disagree on a code after a reorganisation (ONS boundaries lead ONSPD on `E08000038/39` vs `E08000016/19`; GOV.UK lags on the 2023 unitaries), `CODE_ALIASES` re-keys the row onto the code ONSPD actually returns -- an unnamed code is a hard error, not a null name
- `coverage/generate_coverage_map.py` -- Fetches UK LAD boundaries from ArcGIS and generates `coverage.geojson`; status from the `working` flag, `pass_rate` from the last live run

**Tests** (`tests/`):
- `test_ci.py` (marker: `ci`) -- Smoke tests: scripts parse, app boot, `/councils` lists exactly the wired LADs. Runs as pre-commit hook
- `test_councils.py` (marker: `ci`) -- every council module loads, LAD claims are unique and known, and the `_base` helpers (`Address`, `match_address`, `parse_date`, `colour_of`, tidy)
- `test_frontend.py` (marker: `api`) -- API surface tests: landing page, docs, only `/api/v2` mounted, CORS, error cases
- `test_scrape_cache.py` (marker: `api`) -- ICS cache keying with stubbed scrapers: `/{lad}/view/0` never caches, a cache entry never answers for a different scraper, `subscribe`/`download` reject UPRN 0
- `test_deeplinks.py` (marker: `api`) -- deeplink routing for unwired LADs
- `test_v2_routes.py` (marker: `api`) -- the schedule shape (ISO dates ascending, colour, holiday), old IDs in the path, deeplinks, error mapping, subscribe/download, `find` (wired, unwired and NeedsBrowser deeplinks, address API failures, Turnstile), the OpenAPI paths
- `test_bank_holidays.py` (marker: `ci`) -- `holiday_name` per region
- `test_council_wiring.py` (marker: `api`) -- council modules through the routes with stubbed `fetch`: LAD-code IDs (`/find` returns them, two-LAD modules answer to each, every wired LAD is served), old IDs resolving to them, `/councils` params from `requires`, NeedsBrowser and upstream-failure deeplinks, cache beats deeplink, error mapping, refreshing a sidecar written under an old ID (migrated to the LAD code) or an unknown one (ages out as a failure)
- `test_lad_integration.py` (marker: `live`) -- One test per wired LAD (council), not per scraper. Reads `lad_test_cases.json`, runs each case through the real `/api/v2/{lad}/view/{uprn}` route in-process with the params the frontend sends (`{lad}` is the LAD code; jobs dedupe on the module the registry serves, so two LADs sharing a fixture don't race), retries failures once at low concurrency, probes scraper hosts to tell `unreachable` (this machine can't reach it) from `upstream_error`. Case outcomes: pass, empty, input_rejected, deeplink (NeedsBrowser), unreachable, upstream_error, blocked (bot wall; counts as `upstream_error`), scraper_error (a 200 fallback deeplink is classified by its `X-Scrape-Failure` header, as the 503/504 it replaces). Writes `output/lad_integration_output.json` (subset runs via `LAD_CODES` merge into it); status per LAD from `scripts/lad_status.py`. ~7 min for all 350 LADs
- `lad_test_cases.json` -- Generated by `pipeline/shared/generate_lad_test_cases.py`, keyed by LAD code: `{name, scraper_id (module name), fixture_only?, cases: [{id, source: sampled|fixture, label, params}]}`. Sampled cases: an ONSUD postcode in the LAD (4-60 UPRNs), resolved through the address API, keeping a plain-numbered address whose UPRN is in ONSUD. Fixture cases are the serving module's `meta.cases`
- `test_blob_store.py` (marker: `api`) -- the blob store contract against `LocalBlobStore` and `R2BlobStore` (moto)
- `test_refresh_endpoint.py` (marker: `api`) -- `/internal/refresh` auth, sharding, deadline deferral, heartbeat and `/metrics`
- `test_deploy.py` (marker: `docker`) -- Docker stack tests (3): compose boot, scraper loading, static files
- `test_deploy_docker.sh` -- Bash-based Docker deployment test (curl assertions, standalone)
- `conftest.py` -- Test-time env defaults (fresh `DATA_DIR` tempdir per session, address API config)
- `output/lad_integration_output.json` -- Last live run, committed; input to `post_integration.sh` and to the sticky test-case refresh
- `battletest/` -- Ad-hoc shell scripts for load testing, chaos testing, and security checks
- Tests use `pytest-asyncio` with `loop_scope="session"` and `asgi-lifespan` for managing the FastAPI app
- Pytest markers registered in `pyproject.toml`: `ci`, `api`, `live`, `docker`

**CI/CD** (`.github/workflows/deploy.yml`):
- On push to `main`: runs `tests/test_ci.py` only → deploys to Vercel production (`vercel deploy --prod`, a remote build; Vercel's own Git deploys are off in `vercel.json`). `uptime.yml` checks `/status` and the refresh heartbeat every 30 min (a failed run emails). `coverage.yml` (weekly, Monday 06:00 UTC) probes production with `vercel_probe.py --all-sources --write-output`, runs `post_integration.sh`, commits the output, flags, coverage map, badge and sankey, and dispatches a deploy. The local live test (`tests/test_lad_integration.py`) is for development; a local run's output is overwritten by the next Coverage run

**Infrastructure**: Production is Vercel (region lhr1, DNS on Cloudflare) with the ICS cache in Cloudflare R2; `vercel.json`, `[tool.vercel]` in `pyproject.toml` and `.vercelignore` configure it. Docker Compose runs the API alone for local use, with the ICS cache on a named volume (`bins_data`) at `/app/data`. Pre-commit hooks via lefthook run ruff, ty (staged council modules), biome, the CI smoke tests and the daily upstream watch.

## Key Patterns

- Council modules get every query param as an `Address` (`Address.from_params`) and declare what they need in `requires`
- `/{lad}/subscribe/{uprn}` returns iCal format for calendar subscription; the frontend's webcal/Google/Outlook/copy links point at it
- `{lad}` in the path is the LAD code (`E06000001`); `view` echoes the LAD code back even when called with an old scraper ID
- A module sets `transport = Transport.CURL_CFFI` for sites that block on TLS fingerprint, and `verify_tls = False` for broken certificates or old ciphers
- Cache miss on `view`, `subscribe` or `download` triggers an inline scrape guarded by the Redis scrape-lock; parallel requests for the same UPRN poll the cache up to `SCRAPE_LOCK_MAX_WAIT_S` (default 15s) and return 503 on timeout rather than racing
- `subscribe`/`download` stream the on-disk ICS directly; events are merged on write (stable UIDs = sha1(uprn|date|type)) and pruned by `ICS_RETENTION_DAYS`
- Routes include `/status` (system health with uptime/scraper counts) and `/metrics` (Prometheus-format metrics plus ICS cache entry count and last refresh stats)
