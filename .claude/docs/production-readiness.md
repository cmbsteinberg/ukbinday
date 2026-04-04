# Production Readiness

Assessment of what needs addressing before deploying to Hetzner as a public API. Focused on serving users correctly -- making the right API call and returning accurate information in a way they can understand.

## Critical

### 1. Address API depends on a hard-coded CSRF token

**Status: Done**

Server-side address lookup has been removed entirely. The `/addresses/{postcode}` endpoint, `search_addresses()` method, and the Mid Suffolk CSRF token are all gone from the server. Address-to-UPRN lookups now happen exclusively client-side in `api/static/address_lookup.js`, which calls the Mid Suffolk API directly from the browser. The server only handles council lookup (via parquet) and scraper invocation.

This eliminates the CSRF token rotation problem -- any token changes only affect the client-side JS, and a client-side CSRF fetch can be added there independently if needed.

### 2. Silent failures in the postcode-to-scraper chain

**Status: Done**

`get_local_authority()` now raises distinct exceptions instead of returning empty lists:
- `LookupDatabaseError` -- parquet file not loaded (returns 503: "Our postcode lookup service is temporarily unavailable")
- `PostcodeNotFoundError` -- postcode not in database (returns 404: "We couldn't find that postcode in our database")
- No scraper for council -- returns 404 with the council name and a pointer to `/api/v1/councils`

The `/council/{postcode}` route uses a `_resolve_council()` helper that maps these exceptions to the correct HTTP responses.

The new `/api/v1/status` endpoint reports whether the lookup databases loaded successfully (`postcode_lookup: true/false`, `lad_lookup: true/false`).

### 3. Error messages are developer-facing, not user-facing

**Status: Done**

All error responses in `api/routes.py` rewritten to plain language:
- `Scraper error: AttributeError` -> "Something went wrong while fetching your collection schedule. Please try again later."
- `Council site unreachable: ConnectTimeout` -> "We couldn't reach your council's website. The site may be temporarily down -- please try again later."
- `SourceArgumentException` -> "The details provided don't match what this council's system expects. Please check your UPRN and postcode are correct."
- `Council scraper 'x' not found` -> "We don't have a scraper for this council yet. Check /api/v1/councils for the list of supported councils."

### 4. Coverage map shows scraper presence, not whether it works

**Status: Done**

`scripts/coverage/generate_coverage_map.py` now reads `tests/integration_output.json` and computes per-scraper pass rates. The coverage map uses three statuses:
- **Green** (`working`): >= 80% pass rate
- **Orange** (`partial`): > 0% pass rate, or scraper exists but untested
- **Red** (`broken`): 0% pass rate, or no scraper at all

Popups show the council name, status label, and pass rate percentage where available. Regenerate with `uv run python -m scripts.coverage.generate_coverage_map`.

## Fix before deploy

### 5. About 9 councils are completely broken (0% pass rate)

**Status: Done**

Two mechanisms now handle broken scrapers:

**Overridden scrapers** (9 councils in `pipeline/overrides.json`): The HACS `sync.sh` now automatically deletes overridden HACS scraper files after syncing, and `generate_test_lookup.py` skips them when building test_cases.json. The UKBCD replacements (which all pass) are used instead. `lad_lookup.json` already routes most of these to the UKBCD scraper.

**Broken scrapers with no alternative** (38 scrapers): `scripts/generate_disabled_list.py` reads `tests/integration_output.json` and generates `api/data/disabled_scrapers.json` for scrapers with 0% pass rate. The `ScraperRegistry` skips loading disabled scrapers, so they don't appear in `/councils` and users get a clear "not supported" error. To recheck disabled scrapers for recovery: delete the disabled file, run integration tests, and regenerate.

**`pipeline/sync.sh`** is a new top-level script that runs both HACS and UKBCD syncs, then regenerates the disabled list.

### 6. No startup validation

**Status: Done**

`CouncilLookup` now exposes `parquet_loaded` and `lad_loaded` boolean flags. At startup, `main.py` logs `ERROR`-level messages if either file is missing:
- "STARTUP WARNING: postcode_lookup.parquet not loaded -- postcode-to-council lookups will not work"
- "STARTUP WARNING: lad_lookup.json not loaded -- council metadata will be unavailable"

The new `GET /api/v1/status` endpoint returns a `SystemHealth` response with overall status (`healthy`/`degraded`/`unhealthy`) based on which data files loaded.

### 7. Rate limiting is optional

**Status: Done**

The `/api/v1/status` endpoint now reports `redis_connected` and `rate_limiting_active` booleans. It pings Redis to verify actual connectivity rather than just checking if a URL was configured. The startup log already warns when Redis is unavailable.

## Nice to have

### Postcode validation

**Status: Done**

Postcode validation now happens client-side only (in `api/static/address_lookup.js`). The server-side postcode regex was removed along with the address lookup endpoint.

### Slow scraper timeouts

**Status: Done**

`ScraperRegistry.invoke()` now wraps every `source.fetch()` call in `asyncio.wait_for()` with a 30-second timeout (configurable via `SCRAPER_TIMEOUT` constant in `api/services/scraper_registry.py`). On timeout, it raises `ScraperTimeoutError`, which routes handle with HTTP 504 and the message: "Your council's website is taking too long to respond. Please try again later."

### Duplicate address lookup code

**Status: Done**

Resolved by removing the server-side address lookup entirely (item 1). The Mid Suffolk API call now only exists in `api/static/address_lookup.js`.

## Remaining work

All items addressed. To maintain:
- Run `pipeline/sync.sh` to pull upstream changes and refresh the disabled list.
- Periodically recheck disabled scrapers: delete `api/data/disabled_scrapers.json`, run integration tests, regenerate with `uv run python -m scripts.generate_disabled_list`.
