# RobBrad Scraper Integration

This document describes the integration of council scrapers from the [robbrad/UKBinCollectionData](https://github.com/robbrad/UKBinCollectionData) repository into this project.

## Overview

To expand council coverage, we have integrated scrapers from the RobBrad project as a fallback to our primary source ([mampfes/hacs_waste_collection_schedule](https://github.com/mampfes/hacs_waste_collection_schedule)).

The integration follows a "left merge" strategy:
1.  **Priority:** Mampfes scrapers are preferred due to higher quality and native async support.
2.  **Fallback:** RobBrad scrapers are added only for councils/domains not already covered.
3.  **Filtering:** Scrapers requiring Selenium are excluded to maintain a lightweight, headless API.

## Architecture

RobBrad scrapers use a different internal API and are generally synchronous. We use a shim package and adapter pattern to integrate them.

### 1. Local Shim: `api/compat/ukbcd/`

RobBrad scrapers import from `uk_bin_collection.uk_bin_collection.common` and `...get_bin_data`. That upstream package has heavy dependencies (selenium, pandas, holidays). Instead of installing it, we provide a lightweight local shim at `api/compat/ukbcd/` (mirroring how `api/compat/hacs/` shims the Mampfes types).

- **`common.py`** -- Reimplements helpers scrapers actually use: `check_uprn`, `check_postcode`, `check_paon`, `check_usrn`, `date_format`, `days_of_week`, `Region`, `remove_ordinal_indicator_from_date_string`, `parse_header`, `has_numbers`, `contains_date`, `get_weekday_dates_in_period`, `get_dates_every_x_days`, `get_next_occurrence_from_day_month`, `get_next_day_of_week`, `remove_alpha_characters`. Functions that originally used pandas are rewritten with pure `datetime`/`timedelta`. Only external dep is `python-dateutil` (already in project).
- **`get_bin_data.py`** -- Provides `AbstractGetBinDataClass` with `parse_data` as an abstract method and `get_data` using sync httpx.

### 2. Synchronization (`pipeline/ukbcd/sync.sh`)

This script:
*   Performs a shallow clone of the RobBrad repository into `pipeline/upstream/`.
*   Triggers the Python patching script.

### 3. Patching and Adaptation (`pipeline/ukbcd/patch_scrapers.py`)

This script performs the following steps for each RobBrad scraper:
*   **Domain Matching:** Extracts the council URL from RobBrad's `input.json` and normalizes it to a domain.
*   **Blocked Domains:** Skips overly broad domains (`gov.uk`, `calendar.google.com`) that would shadow other lookups.
*   **Coverage Check:** Skips the scraper if the domain is already covered by a non-robbrad (Mampfes) scraper.
*   **Selenium Check:** Skips if the source code imports `selenium` or `webdriver`.
*   **Import Rewriting:** Rewrites `from uk_bin_collection.uk_bin_collection.X import ...` to `from api.compat.ukbcd.X import ...` to use the local shim.
*   **HTTP Conversion:** Converts `requests` to sync `httpx` (`httpx.get`, `httpx.Client`, etc., not `AsyncClient`). The scraper code stays synchronous; the adapter wraps it in `asyncio.to_thread`.
*   **Param Detection:** Reads `input.json` fields (`uprn`, `postcode`, `paon`/`house_number`, `usrn`) to determine which params each scraper needs.
*   **Adapter Generation:** Appends a `Source` class to the file that:
    *   Accepts only the params that scraper actually needs (avoiding `NameError`).
    *   Implements `async def fetch()` which calls `parse_data()` (the actual RobBrad entry point) via `asyncio.to_thread`.
    *   Normalizes the `{"bins": [...]}` dict output into `list[Collection]`, handling both ISO (`YYYY-MM-DD`) and UK (`DD/MM/YYYY`) date formats.
    *   Sets `TITLE` from `wiki_name` in input.json, `URL`, and empty `TEST_CASES`.

### 4. Lookup Integration

The script updates `api/data/admin_scraper_lookup.json`, preserving all existing non-robbrad entries and adding/replacing robbrad entries. Module names are prefixed with `robbrad_` for clarity.

## Usage

To update or re-sync the RobBrad scrapers:

```bash
pipeline/ukbcd/sync.sh
```

## Current State (2026-03-24)

- **114 scrapers generated**, 112 load successfully into the registry
- **2 scrapers fail** (`robbrad_buckinghamshire_council`, `robbrad_newport_city_council`) due to missing `cryptography` package — they use custom SSL cert handling beyond what our shim provides
- **153 domains** skipped as already covered by Mampfes scrapers
- **65 scrapers** skipped due to Selenium dependency
- **2 domains** blocked (`gov.uk`, `calendar.google.com`)

## QA History

### Initial Implementation — Issues Found

The original implementation had several critical bugs that prevented all 116 scrapers from working:

1.  **Missing `uk_bin_collection` package:** Scrapers imported from `uk_bin_collection.uk_bin_collection.common` which was not installed. All scrapers failed with `ModuleNotFoundError` at import time (silently swallowed by the registry).
2.  **Adapter `__init__` bug:** The generated `Source.__init__` conditionally added params to the signature but always assigned all four (`uprn`, `postcode`, `house_number`, `usrn`) in the body, causing `NameError` for any scraper that didn't accept all four.
3.  **Broken async transform:** The patch used `httpx.AsyncClient()` but called sync methods (`.get()`, `.post()`) without `await`, and `parse_data` was never made async. Since the adapter runs via `asyncio.to_thread`, sync httpx is the correct choice.
4.  **Wrong entry point:** The adapter looked for `get_data()` or `get_date_data()`, but RobBrad scrapers use `parse_data()` as their main method.
5.  **Incomplete `requests` conversion:** 72/116 scrapers still had `requests.*` calls after transformation.
6.  **Overly broad domain mappings:** `gov.uk` and `calendar.google.com` were in the lookup, potentially shadowing legitimate council domains.

### Fix (2026-03-24)

All issues resolved by:
- Creating `api/compat/ukbcd/` shim package (like `api/compat/hacs/`)
- Rewriting `pipeline/ukbcd/patch_scrapers.py` from scratch with correct import rewriting, sync httpx conversion, fixed adapter template, correct entry point (`parse_data`), param-aware init generation, and blocked domain filtering
- Regenerating all scrapers and verifying 112/114 import and register successfully

## Maintenance Notes

*   **Adding new shim functions:** If a future RobBrad scraper uses a `common.py` function not yet in our shim, add it to `api/compat/ukbcd/common.py`. Keep implementations dependency-free where possible.
*   **`cryptography` scrapers:** The 2 failing scrapers could be fixed by adding `cryptography` as a project dependency if those councils are needed.
*   **Date Parsing:** The adapter handles ISO and UK slash formats. Councils using unique date strings may require manual parsing adjustments in their specific `robbrad_*.py` file.
*   **Prefix:** All integrated scrapers are named `api/scrapers/robbrad_[sanitized_name].py`.
