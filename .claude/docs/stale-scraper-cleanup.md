# Stale Scraper Cleanup, Duplicate Prevention & Naming Convention

## Problem

Integration tests revealed 83 failures, 76 of which were HTTP 503s. Investigating the 503s uncovered two categories:

1. **Genuine upstream failures** (28 councils) -- council sites down or returning errors, response times >0.5s
2. **Broken scrapers** (14 councils) -- failing instantly (<0.5s), never reaching the council site

The instant failures led to discovering **duplicate scrapers** for the same council. For example, Sheffield existed as both `sheffield_gov_uk.py` (HACS, broken) and `robbrad_sheffield_city_council.py` (UKBCD). Five such duplicates were found on disk.

## Root Cause

- **Old files were never cleaned up.** The skip logic in the UKBCD patch script only prevents *new* writes, it doesn't remove stale files from previous sync runs.
- **The admin lookup accumulated stale entries** like `wasteservices.sheffield.gov.uk -> robbrad_sheffield_city_council`.
- **UKBCD test case generation** merged into the existing `test_cases.json` without stripping old entries, so deleted scrapers kept their test cases.

## Additional Issue: Missing httpx Import

`api/compat/ukbcd/common.py` didn't export `httpx`, so UKBCD scrapers that referenced `httpx` without their own import would crash with `NameError`.

## Changes Made

### 1. Scraper naming convention: `hacs_` and `ukbcd_` prefixes

Renamed all scrapers to use clear source prefixes:
- HACS scrapers: `*_gov_uk.py` -> `hacs_*_gov_uk.py` (217 files)
- UKBCD scrapers: `robbrad_*.py` -> `ukbcd_*.py` (110 files)

Updated across the entire pipeline:
- `pipeline/hacs/patch_scrapers.py` -- outputs `hacs_` prefix on filenames
- `pipeline/hacs/sync.sh` -- cleans `hacs_*.py` before syncing
- `pipeline/ukbcd/patch_scrapers.py` -- outputs `ukbcd_` prefix, scans `hacs_*.py` for prefix matching
- `pipeline/ukbcd/sync.sh` -- cleans `ukbcd_*.py` before patching
- `pipeline/ukbcd/generate_test_lookup.py` -- uses `ukbcd_` prefix, strips stale entries before merging
- `pipeline/ukbcd/check_upstream_fixes.py` -- uses `ukbcd_` prefix
- `pipeline/sync_all.py` -- filters `hacs_*.py`, skips `ukbcd_`
- `pipeline/overrides.json` -- all scraper IDs updated (`hacs_`/`ukbcd_` prefixes)
- `scripts/generate_admin_lookup.py` -- counts by new prefixes
- `api/data/admin_scraper_lookup.json` -- all values prefixed
- `api/data/lad_lookup.json` -- all scraper_id values prefixed
- `tests/test_cases.json` -- all keys prefixed

Note: `requests_fallback`, `curl_cffi_fallback`, and `ssl_verify_disabled` lists in `overrides.json` remain un-prefixed -- they match against upstream source filenames (`src.stem`), not output filenames.

### 2. `pipeline/sync_all.py` -- Wipe all scrapers before syncing

Added step 2 that removes all `.py` files from `api/scrapers/` (except `__init__.py`) before HACS and UKBCD syncs repopulate them. Guarantees no stale files survive across syncs.

### 3. `pipeline/ukbcd/generate_test_lookup.py` -- Strip stale entries

Strips all `ukbcd_*` entries from `test_cases.json` before merging in fresh ones, so deleted scrapers don't keep their test cases.

### 4. `api/compat/ukbcd/common.py` -- Export httpx via wildcard import

Added `import httpx` so all UKBCD scrapers automatically get it through `from api.compat.ukbcd.common import *`. Safety net for when the patch script's `_ensure_httpx_import` misses an edge case.

### 5. Duplicate cleanup

- Deleted 5 duplicate scraper files (Sheffield, Watford, Wolverhampton, Chorley, Eastbourne)
- Removed stale lookup and test case entries

## Integration Test Failure Summary

Of the original 83 failures:

- **76 HTTP 503s**: Split between upstream council site issues (28 slow failures) and scraper code bugs (14 instant failures, 4 with confirmed code bugs)
- **4 HTTP 422s**: Bad test data -- `hacs_charnwood_gov_uk` and `hacs_sefton_gov_uk` use placeholder `uprn=0`
- **3 HTTP 504s**: `hacs_north_norfolk_gov_uk` timing out at 30s

### Confirmed Scraper Code Bugs (from the instant 503s)

| Scraper | Bug |
|---|---|
| `hacs_sheffield_gov_uk` | Bad urllib-to-httpx patch: `urllib.request.Request` with undefined `__urllib_url__`/`__urllib_headers__` variables |
| `hacs_rugby_gov_uk` | `fetch()` is `def` not `async def` -- framework `await` crashes |
| `ukbcd_castlepoint_district_council` | `httpx` not imported (fixed by the `common.py` change) |
