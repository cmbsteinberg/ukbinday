# UKBCD selenium → httpx port: audit trail

This directory is the working record of how we replaced the 42 UKBCD
selenium scrapers with plain `httpx` ports. The ports themselves now live
in `pipeline/ports/`; what remains here is the trail of how we got there,
in three phases.

```
  1. Select        2. Patch                 3. Capture
  ─────────        ────────                 ──────────
  test_selenium    patch_selenium           capture_upstream_xhrs.py
  _scrapers.py     _scrapers.py
       │                │                          │
       ▼                ▼                          ▼
  selenium_test    (AST transpile:           xhr_captures/*.json   ← gitignored
  _results.json     selenium → Playwright)   xhr_capture_summary.json
```

## 1. Select — which upstream selenium scrapers still work?

`test_selenium_scrapers.py` probes every upstream UKBCD selenium scraper
that isn't already covered by a HACS or non-selenium UKBCD scraper (per
`api/data/lad_lookup.json`). For each candidate it invokes upstream's
`collect_data.py` CLI in a disposable `uv run` venv with headless Chrome,
captures the JSON output, and validates it against UKBCD's own
`output.schema`.

**Result:** `selenium_test_results.json` — 29 of 42 pass upstream, 13 are
broken in upstream's own test suite (`SKIP_GET_URL` in UKBCD CI). The 29
are the pool worth porting; the 13 are not candidates.

```
uv run python -m scripts.ukbcd_selenium_port.test_selenium_scrapers [--limit N] [--only NAME,...]
```

## 2. Patch — AST transpile selenium to Playwright

`patch_selenium_scrapers.py` is a Python-to-Python AST rewriter that
converts selenium source into Playwright async source. It strips
`WebDriverWait`/`EC.*`/`time.sleep` (Playwright auto-waits), unwraps
`Select()` into `locator.select_option()`, renames `driver → page`, and
rewrites `create_webdriver()` into Playwright launch boilerplate.

This was the first approach: transpile everything and run the ports
under Lightpanda (our low-footprint headless browser — Hetzner can't
carry full Chromium). It tops out at ~5/42 on Lightpanda because of
iframe / interaction / rendering gaps. That ceiling is what motivated
phase 3.

```
uv run python patch_selenium_scrapers.py <input_file_or_dir> [--dry-run] [--report]
```

## 3. Capture — record what the browser actually sends

Rather than keep fighting Lightpanda's rendering gaps, we observed what
each council's JavaScript actually calls on the wire. Most are plain
JSON or form POSTs behind the browser — no real browser needed.

`capture_upstream_xhrs.py` runs each upstream scraper verbatim under its
own `uv run --no-project --with …` venv, but injects a two-stage
handshake into selenium's lifecycle:

1. Monkey-patch `create_webdriver` to launch Chrome with
   `--remote-debugging-port=<free>`, emit `__READY__`, block on `GO`.
2. Parent reads `__READY__`, attaches Playwright over CDP, wires
   `request`/`response` listeners to every context, writes `GO`.
3. Upstream `get_and_parse_data(url, **kwargs)` drives the browser;
   Playwright observes every request.
4. Monkey-patched `WebDriver.quit` emits `__QUIT_REQUESTED__` and blocks
   on `FINISH` so the parent can drain response bodies before Chrome
   dies.
5. Subprocess prints `__RESULT__<json>`. Parent writes full capture to
   `xhr_captures/{Council}.json` (gitignored) and an aggregate digest
   to `xhr_capture_summary.json`.

A `__RESULT__`-before-`__READY__` path records a "browserless" capture
for scrapers that never touch selenium at all.

```
uv run python -m scripts.ukbcd_selenium_port.capture_upstream_xhrs                  # all eligible
uv run python -m scripts.ukbcd_selenium_port.capture_upstream_xhrs --council X,Y    # subset
```

**Run parameters used for the saved captures:** concurrency 4,
300s/council budget, all 29 captures in ~3 minutes, 6–15s typical per
scrape including Chrome launch, chromedriver pairing, CDP handshake.

### Harness bug worth recording

Pass 1 of the harness called `parse_data('', **payload)` directly with
`input.json` keys — and 11 of 29 scrapers "failed" with 0 XHRs. That
conclusion was wrong; the cross-check against
`selenium_test_results.json` showed the same 11 had all passed days
earlier.

Root cause: upstream's `collect_data.py` CLI maps `-n/--number` →
`paon`, calls `get_data(url)` to pre-fetch HTML, and honours
`skip_get_url`. `input.json` uses `house_number` (not `paon`) and
doesn't mark those flags, so scrapers that read `kwargs.get("paon")`
tripped `check_paon(None)` at line one of `parse_data()`.

Fix: `build_payload` now mirrors the CLI's argparse mapping
(`house_number → paon`, plus `url`/`skip_get_url`/`local_browser`), and
the harness calls `get_and_parse_data(url, **kwargs)` — the framework
entry point — instead of `parse_data` directly. All 29 recovered.

**Lesson:** when a harness re-uses upstream framework code, call the
framework's entry point. Don't re-implement its arg routing.

### Heuristic `httpx_convertible` flag

The summary tags a capture httpx-convertible when at least one non-static
XHR returns a 2xx JSON/text response whose body contains both the UPRN
and either the postcode or a date-ish string. 9 of 29 captures flagged
automatically; 20 more were obviously portable on manual inspection.

The heuristic under-counts because:

- UPRN often rides in query strings, not response bodies (Teignbridge).
- Some POSTs 3xx-redirect with empty bodies (Jadu CXM
  `processsubmission`).
- Some responses use internal IDs instead of UPRN literally (Jadu
  Continuum, Salesforce Aura).
- Some responses are encrypted hex (iTouchVision).
- Noise domains (GTM, analytics, chat widgets) win the top-score race.

## Findings

**29/29 probed scrapers are portable to plain `httpx`.** The backend
landscape is smaller than it looked: four vendors account for ~14
councils, the rest are one-off bespoke flows still straightforward over
HTTP once you can see them.

### Vendor clusters

**IEG4 AchieveForms** (4 captured — Gloucester, NorthDevon, Tendring,
ThreeRivers). Upstream navigates to a page with an AchieveForms iframe;
iframe JS POSTs `{"formValues": {...}}` to
`<council>-self.achieveservice.com/apibroker/runLookup?id=<slug>`.
Response is JSON with collection types and dates. No auth; `id=` is a
public lookup slug. One `httpx.post` per scrape.

**Jadu CXM** (3 captured — StaffordshireMoorlands, Hillingdon, Powys).
Two-shape `/apiserver/…`:

- `GET /apiserver/postcode?postcode=<pc>&callback=jQuery…` — JSONP
  address lookup.
- `POST /apiserver/formsservice/http/processsubmission?pageSessionId=<sid>` —
  form-encoded, UPRN in body, 303 → `GET /findyourbinday?pageSessionId=<sid>`
  renders the result HTML.

Seed `pageSessionId` from the initial page load, strip the JSONP
callback wrapper, 2–3 HTTP calls. Any UKBCD scraper targeting
`/apiserver/postcode?callback=…` is Jadu CXM — Hillingdon and Powys were
previously assumed to be singletons.

**iTouchVision** (4 captured — BlaenauGwent, EpsomAndEwell, Hyndburn,
Winchester). Public page redirects to a React SPA at
`iportal.itouchvision.com/icollectionday/collection-day/?uuid=<UUID>`
(or `iapp.itouchvision.com`, or a bespoke council subdomain). SPA calls
`GET https://iweb.itouchvision.com/portal/itouchvision/kmbd/address` and
`/collectionDay`.

Response bodies are **AES-encrypted hex blobs** decrypted client-side
from a key embedded in `main.<hash>.js`. We didn't re-reverse the
crypto; HACS already has `iapp_itouchvision_com` reverse-engineered, so
we ported the HACS decryption protocol into
`api/compat/hacs/itouchvision.py` and wrote 6 thin UKBCD scraper
wrappers (`hacs_itv_*.py`). Epsom and Ewell wasn't in upstream HACS
config — its client/council IDs (138/140) were reverse-engineered from
the portal's `igetclientdetails` endpoint.

**Jadu Continuum** (2 captured — Sevenoaks, Hertsmere). Hosts at
`<council>-dc-host01.oncreate.app` or `<council>-services.onmats.com`,
path prefix `/w/webpage/…`. Flow: `POST /w/webpage/waste-collection-day`
→ session metadata; `POST …?webpage_subpage_id=PAG…` with
`code_action=search&code_params={"search_item":"<pc>"}` → JSON address
list; `POST …` with `code_action=address_selected` and
`GET /w/webpage/<template_id>?webpage_token=<t>` → HTML with dates.
Four-request `httpx.AsyncClient` with cookie jar.

**Salesforce Aura** (1 captured — ForestOfDean). `POST
https://community.fdean.gov.uk/s/sfsites/aura?r=<n>&aura.LookupPageId=…`
with an Aura "message" JSON carrying `params.uprn`. Needs
`aura.token` + `fwuid` harvested from the initial Salesforce page —
heavier than Jadu but well-documented.

### Per-council singletons

Pure Tier 0, single endpoint:

- **Teignbridge** — `GET /repositories/hidden-pages/bin-finder?uprn=<uprn>`
  returns HTML with the schedule. Easiest port in the set.
- **Basildon** — upstream never calls `create_webdriver`; flow is
  `POST https://basildonportal.azurewebsites.net/api/getPropertyRefuseInformation`.
- **DumfriesAndGalloway**, **Edinburgh** — captures emitted 0 XHRs with
  a successful result → upstream is already plain HTTP. Browserless.

Tier 0, confirmed payload URL:

| Council | Endpoint |
|---|---|
| ArgyllandBute | `POST www.argyll-bute.gov.uk/rubbish-and-recycling/household-waste/bin-collection` (HTML) |
| NewForest | `POST forms.newforest.gov.uk/ufs/ufsajax?…` (Oracle UFS) |
| Northumberland | `POST bincollection.northumberland.gov.uk/address-select` |
| Torbay | `POST selfservice-torbay.servicebuilder.co.uk/core/address…` |
| Wychavon | `POST selfservice.wychavon.gov.uk/sw2AddressLookupWS/jaxrs/…` |

Heuristic missed (bespoke single POST each, cluster not worth
extracting):

- **Somerset** (10 XHRs) — form on `somerset.gov.uk/collection-days`.
- **Ceredigion** (68 XHRs) — form on
  `ceredigion.gov.uk/resident/bins-recycling/`; the heuristic's
  candidate URL was the cookie banner, ignore.
- **MidSuffolk** (131 XHRs) — chat-widget noise in heuristic candidate;
  real backend is a single POST.
- **MidUlster** (41 XHRs) — bespoke flow on
  `midulstercouncil.org/resident/bins-recycling`.
- **TestValley** (9 XHRs) — small flow, single POST.
- **BrightonAndHove** (20 XHRs) —
  `enviroservices.brighton-hove.gov.uk/widgets/HTMLSnippet/...`, widget
  iframe pattern.

None needs a browser at runtime.

### Scorecard

| Bucket | Count |
|---|---|
| Portable as plain `httpx` (capture + flow known) | 22 |
| iTouchVision cluster (ported via HACS `hacs_itv_*.py`) | 6 |
| Upstream broken in manifest | 13 |

The ports themselves now live in `pipeline/ports/` (22 plain-httpx) and
`api/scrapers/hacs_itv_*.py` (6 iTouchVision via the HACS decryption
shim in `api/compat/hacs/itouchvision.py`). Upstream-broken councils
remain untouched.
