# Input.json-Driven Sync Pipeline

## Problem

The old sync pipeline pulled in all HACS scrapers blindly, then discovered stale ones reactively via integration test failures. This meant:

- Scrapers for defunct councils (e.g. Allerdale, merged into Cumberland) were synced, tested, and failed
- `disabled_scrapers.json` was generated after the fact from 0% pass rates
- No distinction between "council doesn't exist anymore" and "scraper is broken but council is real"
- Wasted CI time testing scrapers that could never work

## Solution

UKBCD's `input.json` is now the source of truth for which councils need coverage. The new `pipeline/sync_all.py` orchestrator drives the entire sync process.

### Full Pipeline Flow

```
1.  Fetch input.json from UKBCD GitHub (334 council entries)
2.  Extract needed gov.uk prefixes (e.g. "aberdeencity", "cumberland")
3.  Run HACS sync (clone, patch, copy ~235 scrapers)
4.  Filter: remove HACS scrapers whose gov.uk prefix isn't in input.json (~20 removed)
5.  Regenerate admin_scraper_lookup.json (post-filter)
6.  Run UKBCD sync (fills gaps for councils without HACS coverage)
7.  Final admin lookup regeneration
8.  Regenerate test cases (HACS + UKBCD)
9.  Regenerate LAD lookup (postcode -> council -> scraper)
10. Regenerate disabled_scrapers.json (if integration results exist)
```

After integration tests run, `test_integration.py` automatically regenerates:
- `disabled_scrapers.json` (scrapers with 0% pass rate)
- Coverage map (`coverage.geojson` + `coverage_map.html`)

### Domain Matching

Matching uses the `gov.uk` prefix -- the subdomain component immediately before `.gov.uk` (or `.gov.wales`):

- `https://www.allerdale.gov.uk` -> `allerdale`
- `https://online.aberdeenshire.gov.uk` -> `aberdeenshire`
- `https://bins.shropshire.gov.uk` -> `shropshire`

This handles subdomains cleanly (e.g. `online.`, `bins.`, `my.` prefixes are ignored). As a fallback, the scraper filename is also checked (e.g. `solihull_gov_uk` -> `solihull`).

Both `sync_all.py` (filtering stale HACS) and `ukbcd/patch_scrapers.py` (deciding if HACS already covers a council) match by gov.uk prefix. This catches ~21 additional HACS matches that full-domain matching missed, avoiding redundant UKBCD scrapers.

### Key Files

| File | Role |
|------|------|
| `pipeline/sync_all.py` | Orchestrator: fetches input.json, runs syncs, filters, regenerates everything |
| `pipeline/sync.sh` | Shell entry point (delegates to sync_all.py) |
| `pipeline/shared.py` | `extract_gov_uk_prefix()` utility |
| `pipeline/hacs/sync.sh` | HACS clone + patch |
| `pipeline/ukbcd/sync.sh` | UKBCD clone + patch |
| `tests/test_integration.py` | After tests: regenerates coverage map + disabled list |
| `lefthook.yaml` | Pre-commit runs `pipeline/sync.sh` |

### Usage

```bash
# Full sync -- scrapers, test cases, lookups, everything
pipeline/sync.sh

# Or directly via Python
uv run python -m pipeline.sync_all

# With unmerged UKBCD PR checking
pipeline/sync.sh --include-unmerged

# Integration tests (auto-regenerates coverage map + disabled list)
uv run pytest tests/test_integration.py -v
```

### Impact

- ~20 stale HACS scrapers filtered out at sync time (allerdale, east_northamptonshire, richmondshire, etc.)
- ~21 more councils correctly use their HACS scraper instead of a redundant UKBCD one
- Test cases regenerated after filtering (no stale test entries)
- Coverage map and disabled list auto-regenerated after integration tests
- Single entry point (`pipeline/sync.sh`) does everything

### Overrides vs Filtering

- **Filtered out**: Council not in input.json at all (defunct/merged). Scraper never enters `api/scrapers/`.
- **Overridden** (`overrides.json`): Council exists but HACS scraper is broken; UKBCD alternative is used instead.
- **Disabled** (`disabled_scrapers.json`): Council exists, scraper exists, but has 0% integration test pass rate.
