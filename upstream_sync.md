# The upstream sync (retired)

Until October 2026 every council scraper here was a patched copy of one from two community
projects. The pipeline that produced them was removed once all wired councils had been
rewritten as modules in `api/councils/`. This note records how it worked. The code itself is
preserved at the git tag `upstream-sync-final`:

```bash
git checkout upstream-sync-final      # full tree with pipeline/, api/scrapers/, api/compat/
git show upstream-sync-final:pipeline/hacs/patch_scrapers.py
```

## Sources

| Repo | Prefix | Upstream file | Role |
|---|---|---|---|
| [mampfes/hacs_waste_collection_schedule](https://github.com/mampfes/hacs_waste_collection_schedule) | `hacs_` | `custom_components/waste_collection_schedule/waste_collection_schedule/source/<x>.py` | primary (~235 scrapers) |
| [robbrad/UKBinCollectionData](https://github.com/robbrad/UKBinCollectionData) | `ukbcd_` | `uk_bin_collection/uk_bin_collection/councils/<Name>.py` | gap filler (~73) |

hacs won wherever both had a council, except where `pipeline/routing.json` (`hacs_to_ukbcd`,
23 entries, each with a reason such as `unreachable` or `404_not_found`) switched a failing
hacs scraper to its ukbcd equivalent.

## Flow (`pipeline/sync.sh` -> `pipeline/sync_all.py`)

1. Build council identifiers from UKBCD's `uk_bin_collection/tests/input.json` aliases
   (which councils have a scraper) and `pipeline/data/lad_base.json` (which councils exist;
   the sync could never add or drop a council).
2. Wipe `api/scrapers/` so stale files never lingered.
3. **hacs** (`pipeline/hacs/sync.sh`): shallow-clone at the latest commit (recorded in
   `pipeline/hacs/.upstream_version`), copy the UK `source/` files, and patch them:
   - `patch_scrapers.py` is an AST transform from sync `requests` to async `httpx`. It finds
     sessions, adapters and every method that makes a request (following `self.` calls so
     callers become `async` too), then edits source by AST node positions so comments and
     formatting survive. It also handles `session.mount` adapters, per-class SSL settings
     and `time.sleep` -> `asyncio.sleep`.
   - `patch_overrides.json` sends specific scrapers through `curl_cffi` (TLS fingerprint
     blocks) or `requests` in a thread (Cloudflare) instead of plain httpx.
   - `patch_compat.py` rewrites hacs' shared service modules (AchieveForms,
     FirmstepSelfService, WhitespaceWRP, SSLError) into async versions in
     `api/compat/hacs/`, so scrapers didn't pull in Home Assistant.
4. Drop hacs scrapers that matched no council identifier.
5. **ukbcd** (`pipeline/ukbcd/sync.sh` + `patch_scrapers.py`): shallow-clone, skip
   councils hacs already covered and anything needing Selenium, rewrite imports onto the
   lightweight shims in `api/compat/ukbcd/` (no pandas/selenium), convert `requests` to sync
   httpx, and append a `Source` adapter so each scraper exposed the hacs-style
   `async fetch()`. It wrote `pipeline/data/scraper_lad_map.json` (LAD -> scraper).
   `--include-unmerged` also pulled scrapers from open UKBCD PRs.
6. Wire leftovers (`pipeline/lad_overrides.json` for wrong or third-party council URLs,
   wrong LAD codes, recodes) and compose `api/data/lad_lookup.json`.
7. Regenerate `tests/test_cases.json` from each scraper's `TEST_CASES`
   (`generate_test_lookup.py` per source), then the postcode lookup.

`pipeline/ports/` held hand-written ports for scrapers the patcher couldn't handle, mostly
UKBCD Selenium scrapers redone as plain httpx form flows (IEG4 AchieveForms, Oracle eBase,
GOSS, Jadu, oncreate), copied into `api/scrapers/` on each sync.

## Why it went

Patched copies broke in ways the patcher couldn't see, every sync could undo a local fix,
and two scraper shapes plus two shim layers had to be kept working. The modules in
`api/councils/` share one contract (`scraper_contract.md`), and each began as a port of the
scraper named by its old ID in `api/councils/_aliases.json`.

Upstream fixes now arrive by hand. `scripts/upstream_watch.sh` lists new upstream commits
touching the source file of a council we serve, using those old IDs to find the file.
