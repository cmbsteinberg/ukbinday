# Full coverage — TODO

## 1. True council mapping — DONE

`lad_lookup.json` is now 361 entries pinned to the distinct LAD codes in
`onspd_postcode_lad.parquet` (363 minus `L99999999`/`M99999999`, which are
Channel Islands/Isle of Man pseudo-codes, not councils), named from ONS
`LAD25NM`, with `govuk_url` from GOV.UK Local Links Manager `LGSL524`
(357 of 361; missing for `E06000063`, `E06000064`, `E06000066`, `W06000024`).
22 codes added, 2 stale retired (`E07000097`, `E07000165`). Ownership split:
`pipeline/data/lad_base.json` (ONS/GOV.UK ground truth) + `scraper_lad_map.json`
(input.json/overrides wiring) → composed into `api/data/lad_lookup.json`.
`scripts/lookup/fetch_latest.sh` version-checks all four sources. See AGENTS.md.

**Left over from the rebuild:**
- `pipeline/data/onspd_postcode_lad.parquet` is stamped `onspd_edition: unknown`
  — the edition of the committed artifact was never recorded. Upstream is now
  `ONSPD_AUG_2026` (ours predates it); the next `fetch_latest.sh` run stamps a
  real edition. `onsud_uprn_postcode.parquet` is unstamped (88MB rewrite, no
  benefit until refetch).
- Orphan scrapers: 29 were wired to no LAD. Resolved by adding 8
  `lad_overrides.json` entries (wired 315 → 321, unwired LADs 46 → 40):
  Basildon `E07000066`, Knowsley `E08000011`, Teignbridge `E07000045`, Epping
  Forest `E07000072` (input.json URL is a third-party portal or, for
  Teignbridge, literally `google.co.uk`, so domain matching couldn't reach the
  scraper); East Herts `E07000242` (recoded); Gosport `E07000088` and Stroud
  `E07000082` (input.json gave Gosport Stroud's `LAD24CD`); Blackburn with
  Darwen `E06000008` (input.json listed Blackburn with **Blaby's** URL, so the
  LAD served Blaby's bin days).
  Remaining ~18 orphans are duplicate hacs/ukbcd/port files for an
  already-wired council — benign, since HACS retention matches on a looser key
  (prefix/name) than wiring (exact domain). `ukbcd_harrogate_borough_council`
  and `ukbcd_eden_district_council` cover fractions of successor authorities
  (North Yorkshire `E06000065`, Westmorland and Furness `E06000064`) and need
  postcode-level sub-routing, not a LAD wire. `ukbcd_environment_first` has no
  `LAD24CD` upstream; Lewes and Eastbourne are already wired.
- LADs with no scraper — see §2 open-work types (build backlog vs
  settled placeholders).

## 1a. Original analysis (kept for context)

**Problem:** `lad_lookup.json` (343) built from `input.json` LAD24CD. Not ground truth — we don't know what we don't know.

**Pin to latest codes via UPRN table (correct):**
- `pipeline/data/onspd_postcode_lad.parquet` (363 distinct `oslaua` incl. L/M) + `onsud_uprn_postcode.parquet` is the source for `api/data/postcode_lookup.parquet` — this is what `/council/{postcode}` actually resolves (`api/services/council_lookup.py:84`). It is newer than `LAD_MAY_2025` boundaries (361) — e.g. it has `E07000242` (East Herts new) not `E07000097` (old), but still `E08000016/19` not `E08000038/39` (Boundary/ONSPD lag).
- **Decision:** pin `lad_lookup` to **ONSPD+ONSUD distinct codes** (363 incl. 2 non-UK) + **GOV.UK Local Links Manager** `LGSL524/LGIL8` (355 GSS→rubbish URL) as URL source. Boundary file only for `coverage.geojson` map, not for lookup. Store ONSPD version in parquet metadata and update monthly.
- **We don't have this yet:** `scripts/lookup/create_lookup_table.py:17` is manual (`Download ONSPD multi_csv zip, unzip, and run COPY ...`). Ideally add `scripts/lookup/fetch_latest.sh` to `curl` latest ONSPD (ONS Geoportal), ONSUD, LAD boundaries (`LAD_MAY_2025_UK_BUC` `scripts/coverage/generate_coverage_map.py:10`), and GOV.UK CSV in one go — then `uv run python -m scripts.lookup.create_lookup_table` is a true one-liner.
  - *Note:* ONSPD zip is `~2.3GB` (Nov 2025, growing) — `duckdb` can't slim the download (still has to pull `Data/multi_csv/*.csv`). Script should version-check (`ETag`/`.upstream_version` + `curl -z`) and cache `~/ONSPD_*` in CI, so we keep committed `15MB` `onspd_postcode_lad.parquet` as artifact and only re-download when ONS cuts a new month.

**Gap:** 22 in parquet not in `lad_lookup` (Rutland E06000017, Southend E06000033, Westminster E09000033 etc — all have GOV.UK URLs), 2 stale in `lad_lookup` not in parquet (E07000097, E07000165), 26 null scrapers all have GOV.UK deeplinks.

**Do:**
- Regenerate `lad_lookup.json` from `363` parquet codes + GOV.UK URL, then attach `scraper_id` from `input.json`/`lad_overrides.json`.
- Add 22, retire 2 stale (Harrogate now N.Yorks E06000065, East Herts already E07000242 in parquet).

## 2. Full coverage on existing councils

**Current:** read live, never snapshot — wired vs unwired is null
`scraper_id` in `api/data/lad_lookup.json`, broken is wired plus
`working: false` (written by `annotate_lad_working` from
`tests/output/integration_output.json`); badge, README sankey and
`coverage.geojson` regen via `./pipeline/ci/post_integration.sh`, which
runs automatically after integration runs.

**Done since:** Icons sync blocker fixed (`api/compat/hacs/icons.py` +
`pipeline/hacs/sync.sh`); stale UPRNs resampled
(`pipeline/shared/enrich_test_postcodes.py`); XHR recapture for the 4 port
regressions + North Devon AchieveForms rewrite; 7 scopeless wired (321 → 328):
Worthing `E07000229` free via the shared Adur backend (verified with Worthing
UPRNs from the ONSUD/ONSPD join, auto-wires on GOV.UK domain match);
Babergh `E07000200` + Mid Suffolk `E07000203` via two per-LAD Placecube ports
(the shared HACS source is unusable — its required `council` selector collides
with the API's reserved `council` query key; base suppressed via
`routing.json`); Cotswold `E07000079`, Forest of Dean `E07000080`, East Suffolk
`E07000244` restored from `pipeline/upstream` (the pre-fix council filter had
deleted them); Powys `W06000023` via a GOSS Forms port (GET `binday` tokens →
form POST with UPRN alone → `bdl-card` dates).

**Triage rule (port vs deeplink)** — full version + sibling-template table in
`pipeline/ports/README.md`. Deeplink only if all three hold: (1) no *working*
plain-HTTP path (broken HACS / Selenium-only counts as absent); (2) a 30–60
min probe finds no data endpoint (`httpx_convertible: false` means "probe",
never "browser"); (3) stateful proprietary runtime (Mendix, Aura w/o fallback,
captcha/Turnstile) — this gate is the crux. Target selection (council bin page
> GOV.UK page > nothing) is separate; "nothing" (Merthyr `W06000024`, no
GOV.UK URL either) is discovery backlog, still deeplink-shaped, never 404.

**Verdicts from the captured 7:** Brighton = deeplink (Mendix; needs a
`{deeplink}` response — 404 today); Hertsmere + Sevenoaks = Oncreate-family
port pair (token replay, no captcha; Hertsmere's `round-search` needs
round→date mapping); Staffs Moorlands undecided (`bins.*` PublicDashboard SPA,
one more probe for the data endpoint).

**Verdicts 2026-09-04 (live-probed, 4 councils):**
- **Isles of Scilly `E06000053` = deeplink, settled.** No address lookup
  exists at all — static round map + area table, no kerbside collection off
  St Mary's/St Martin's. Deeplinks to its GOV.UK page (`scilly.gov.uk/waste`,
  live).
- **North East Derbyshire `E07000038` = deeplink, settled.** Firmstep
  `Check_your_Bin_Day` is retired (302s, the button is commented out of the
  council page); only static Calendar A/B PDFs remain and `apibroker` 403s.
  Deeplinks to its GOV.UK bin-dates page. Its stale Firmstep `url` is gone
  from `lad_lookup.json` now the code is blocklisted.
- **Kensington and Chelsea `E09000020` = port, backlog.** Not a deeplink: a
  plain ASP.NET street form, no proprietary runtime, so gate (3) fails.
- **West Devon `E07000047` = port, backlog.** Not a deeplink: the FCC JSON
  backend works end-to-end (sibling of the other FCC councils).

**Deeplink targets:** the default target is the entry's own `url`, else
`govuk_url` (`api/services/deeplinks.py`). Where that default is dead, add the
code to `deeplink_urls` in `lad_overrides.json` — `compose()` writes it into
the entry's `url`, so a wired scraper's URL always wins and an override on a
wired code is inert (logged as a warning). One entry today: Fylde
`E07000119`, whose GOV.UK `/refuse` 404s after the portal moved to
`new.fylde.gov.uk/wasteportal`. Scilly and NE Derbyshire need no override —
their GOV.UK pages are live and correct. Covered by `tests/test_deeplinks.py`
(service resolution, `/lookup` 200+deeplink, `/calendar` 302, and the
data invariants: every unwired LAD has a target, every override reaches the
lookup, every blocklist reason ships as `status`).

**Open work by type** (live lists via the queries above, not snapshots):

- **Build backlog (unwired, no blocklist):** each needs a 30–60 min
  port-vs-deeplink probe per the triage rule; Brighton is the deeplink
  reference case (spec done, `{deeplink}` response implementation open).
- **Settled placeholders (unwired, blocklisted in `unwired_lads`):**
  test-fixture only — the shared UKBCD Google-calendar dummy
  (`api/services/scraper_registry.py:19`, 2026-09-03: identical bins for
  all, `/lookup` 503d), not Selenium in general. Re-wire only on real
  per-council feeds; the generic calendar adapter needs a `?url=`
  allowlist design first (SSRF surface). Selenium-backed councils with
  real entries (Halton, Brighton, etc.) are build backlog, not settled.
  Resolved 2026-09-30 — of the original 10, 7 ported, 2 settled as
  deeplinks, 1 open:
  | Council | Outcome | Mechanism |
  |---|---|---|
  | Bassetlaw | port (address) | ReCollect EU `address-suggest` → place UUID → events |
  | Brentwood | port (UPRN) | open GeoServer WFS UPRN → route PDF calendar (ends Nov 2026) |
  | Ribble Valley | port (postcode+address) | Jadu directory → weekday PDF, cell colour = bin (to Mar 2027) |
  | Rossendale | port (postcode+address) | Jadu directory → zone PDF with printed dates (to Mar 2027) |
  | Trafford | port (UPRN+postcode) | POST apps.trafford → A/B PDF via curl_cffi, shape colour = bin |
  | Newry | port (postcode+address) | POST postcode → zone PDF box layout (to Apr 2027, bank-holiday swaps skipped) |
  | Torfaen | port (UPRN) | shared iTouchVision helper, client 80 / council 397 |
  | Causeway | deeplink, settled | 4 area PDFs, colour-only week marking, no address→area mapping |
  | Derry | deeplink, settled | one generic calendar image; Sentireal app backend not public |
  | Isle of Wight | **open** | `digitalservices.iow.gov.uk` refuses TCP from our dev egress — re-probe from the Hetzner box (Blazor negotiate + GOSS `pubKey` forms) |
  PDF-backed ports stop returning dates when the council's calendar ends;
  expect yearly breakage until the council republishes.
- **Broken-but-wired triage:** one retry, then classify — slow-503 (site
  down, wait), fast-503 (block, consider `curl_cffi` flag), partial
  (stale UPRN — resample via `_sample_uprns_for_lad`), 422 (site-side
  validation or a dead finder like Calderdale's notice page — read the
  council page before resampling).
- **Port debt (our code, fix first):** North Devon, Three Rivers.
- **Probed, port confirmed, not built:** none. Kensington and Chelsea
  `E09000020` (street form, weekday-only) and West Devon `E07000047` (FCC
  JSON, next date per service) ported 2026-09-30.
- **Integration harness — UPRN-0 cache collision (open):** cases without a
  `uprn` hit `/lookup/0`, and `get_or_scrape` caches on UPRN alone, so every
  address-only case after the first is served the first one's cached data —
  false passes (~77 cases). Production is unaffected (real UPRNs from the
  address picker). Fixed 2026-09-30: the 40s hard limit no longer counts
  semaphore queue time (it was timing out ~250 cases on slower links).
- **Zero-signal (wired, zero test rows):** Antrim, Dartford, South Staffs
  — probe before building (Bridgend pattern: upstream fixtures beat
  resampling; ONS samples can return councils-unknown UPRNs).
- **Orphan noise:** failing scraper files with no LAD wired (e.g.
  Hillingdon-HACS while the port passes) — ignore unless wired.
- **Badge vs `working` disagree (pre-existing, 2026-09-04):** the badge says
  334/341 while `annotate_lad_working` says 331 working, because
  `scripts/generate_sankey.py:56` counts a council with *no* test rows as
  passing (`results is None or results["pass"] > 0`) — the zero-signal
  councils. Pick one definition; untested is not passing.

**Settled pattern (first use 2026-09-03, calendar placeholders):**
unwire + blocklist in `unwired_lads`, strip in `sync_all` post-merge and in
`compose()`, reason shipped as entry `status`, serving path disabled
(registry passthrough). Reuse for future settlements.

## 3. Scraper family templates

335 scrapers, ~half bespoke — but four families are large enough to warrant
shared clients + patch-time definitions (extract URLs/lookup IDs/field maps
by AST, emit config not logic): AchieveForms ~42, Whitespace ~21,
ASPX-postback ~21, ICS ~12. Rest stays hand-written.
