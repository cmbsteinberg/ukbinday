# UKBCD Selenium Scraper Ports

Draft ports of UKBCD selenium scrapers to plain `httpx` + `BeautifulSoup`.
Each file follows the HACS scraper pattern (`Source` class, `TITLE`, `URL`, `TEST_CASES`, `async fetch()`).

## Ported (15 councils)

### Browserless (no XHR traffic — upstream never used the browser for data)
| File | Council | Notes |
|------|---------|-------|
| `dumfries_and_galloway_council.py` | Dumfries & Galloway | Downloads ICS calendar by UPRN |

### IEG4 AchieveForms cluster
| File | Council | Lookup chain |
|------|---------|-------------|
| `tendring_district_council.py` | Tendring | Auth → schedule lookup with UPRN |
| `three_rivers_district_council.py` | Three Rivers | Auth → token → schedule with UPRN |
| `gloucester_city_council.py` | Gloucester City | Auth → bin config → individual date lookups |
| `north_devon_council.py` | North Devon | Auth → USRN → token → date range → HTML schedule |

### Bespoke singletons
| File | Council | Pattern |
|------|---------|---------|
| `argyll_and_bute_council.py` | Argyll & Bute | Drupal form POST (postcode → UPRN → HTML table) |
| `antrim_and_newtownabbey_council.py` | Antrim & Newtownabbey | Plain GET with address `Id` → `div.feature-box.bins` dates (id-path only; Bryson UPRN path dead) |
| `northumberland_council.py` | Northumberland | CSRF form (postcode → UPRN → HTML table) |
| `torbay_council.py` | Torbay | ServiceBuilder form (renderform + UPRN → HTML) |
| `wychavon_district_council.py` | Wychavon | Address lookup API + form POST → HTML table |
| `new_forest_council.py` | New Forest | Oracle eBase/UFS form (postcode → UPRN → JSON) |
| `ceredigion_county_council.py` | Ceredigion | Oracle eBase/UFS form (postcode → address → results page) |
| `mid_ulster_district_council.py` | Mid Ulster | Azure REST API (`/api/addresses` + `/api/collectiondates`) |
| `hillingdon_council.py` | Hillingdon | Jadu CXM JSON-RPC (`/apiserver/ajaxlibrary`) — returns day name + bin types |

### GOSS Forms cluster (same platform family as Hillingdon, different flow)
| File | Council | Lookup chain |
|------|---------|-------------|
| `port_powys_council.py` | Powys | GET `binday` (tokens in hidden inputs) → POST form with UPRN → `bdl-card` dates |

### Oncreate-family (`oncreate.app` / `onmats.com`, `webpage_token` + `webpage_subpage_id`)
| File | Council | Lookup chain |
|------|---------|--------------|
| `port_hertsmere_borough_council.py` | Hertsmere | GET landing (cookie) → AJAX dynamic page (fresh token + form fields + typeahead params) → `html_get_type_ahead_results` typeahead → search-form POST with record id → Collection-days table. Source publishes weekdays only, so dates are next-occurrence projections (no multi-week fabrication) |

### Placecube/Liferay cluster (shared Babergh & Mid Suffolk service)
| File | Council | Lookup chain |
|------|---------|-------------|
| `port_babergh_district_council.py` | Babergh | CSRF seed → portlet POST with UPRN → HTML table. Split per-LAD because the upstream HACS source's required `council` selector collides with the API's reserved `council` query key |
| `port_mid_suffolk_district_council.py` | Mid Suffolk | Same, hardcoded to the Mid Suffolk backend |

### Ported 2026-09-30 (former test-fixture placeholders + probe backlog)
| File | Council | Pattern |
|------|---------|---------|
| `port_west_devon_borough_council.py` | West Devon | FCC CodeIgniter (`fcc_session_token` → `getcollectiondetails` JSON), sibling of South Hams |
| `port_kensington_and_chelsea_council.py` | Kensington & Chelsea | ASP.NET Core street form → weekday table (weekday-only projections) |
| `port_bassetlaw_district_council.py` | Bassetlaw | ReCollect EU (`api.eu.recollect.net`, area `BassetlawUK`, svc 50015) — address text, not UPRN |
| `port_brentwood_borough_council.py` | Brentwood | GeoServer WFS (UPRN → route + calendar link) → route PDF (filled/outlined boxes) |
| `port_ribble_valley_borough_council.py` | Ribble Valley | Jadu directory → weekday PDF (cell hue = blue/green week) |
| `port_rossendale_borough_council.py` | Rossendale | Jadu directory → zone PDF with printed dates |
| `port_trafford_council.py` | Trafford | POST postcode → inline JSON → A/B PDF (curl_cffi; vector-shape colour = bin) |
| `port_newry_mourne_and_down_council.py` | Newry, Mourne & Down | POST postcode → zone PDF box layout (digits are outlines, not text) |
| `port_torfaen_county_borough_council.py` | Torfaen | Shared iTouchVision helper (client 80, council 397) |

### Whitespace WRP (shared client `api/compat/whitespace.py`)
`hacs_{lancaster,midsussex,norwich,waverley}_gov_uk.py` and `ukbcd_{lancaster_city,norwich_city,surrey_heath_borough,waverley_borough,woking_borough}_council.py` are config-only wrappers over `fetch_collections(WhitespaceConfig, ...)`. They keep the upstream filenames so `_copy_ports` overwrites the synced originals — upstream fixes to these 9 no longer flow in.

## Triage rule: port vs deeplink

For scopeless LADs, deeplink (serve the GOV.UK/council URL, no scraper) only if **all three** hold; otherwise port it:

1. **No working plain-HTTP path available off the shelf.** An upstream file counts only if it actually runs — broken HACS sources and Selenium-only UKBCD ones count as absent. (Forest of Dean looked Salesforce-only until its working HACS path surfaced.)
2. **A short probe finds no data endpoint.** Cap at ~30–60 min per council: replay candidate XHRs with a test UPRN/postcode. `httpx_convertible: false` in the capture summary means "needs human probe", never "needs browser" — Mid Suffolk scored false (its candidate URL was a live-chat tracker) yet ports as one CSRF + POST.
3. **The platform is a stateful proprietary runtime.** Mendix (`mxui`/`mxclientsystem`, empty shell), Salesforce Aura/Lightning with no server fallback, anything behind captcha/Turnstile. Token-replayable low-code forms (GOSS `apiserver`/Forms, AchieveForms, Placecube, Oncreate-family `webpage_token` flows) fail this gate — they are ports, even when fiddly. **This gate is the crux; 1–2 are just cheap elimination around it.**

Target selection (council bin page > GOV.UK page > nothing) is a separate follow-on step, not part of the decision. "Nothing" (e.g. Merthyr Tydfil, which has no GOV.UK link either) is a discovery backlog item, still served deeplink-shaped, never 404.

## Sibling templates

Before porting from scratch, check whether the council's platform already has a template. Copy the lookup chain, keep the parse:

| Platform signal | Template port | Flow to reuse |
|---|---|---|
| GOSS `/apiserver/ajaxlibrary` JSON-RPC (`*.DatasourceQueries.alloy.*`) | `port_hillingdon_council.py` | POST JSON-RPC with UPRN → day name + bin types |
| GOSS Forms (`/apiserver/formsservice/http/processsubmission`, `*_FORM` hidden inputs) | `port_powys_council.py` | GET page tokens → POST form with UPRN (+ NEXT button field) → card/table parse |
| IEG4 AchieveForms (`/apibroker/runLookup`, `AF-` form/stage IDs) | `port_north_devon_council.py` | Auth → lookup chain with session/token IDs scraped from page |
| Placecube/Liferay portlet (`mvcRenderCommandName`, `p_p_id`) | `port_babergh_district_council.py` | CSRF seed → portlet POST with UPRN → table parse |
| Oncreate-family (`oncreate.app` / `onmats.com`, `webpage_token` + `webpage_subpage_id`) | `port_hertsmere_borough_council.py` | GET page tokens → `/w/ajax` typeahead → search-form POST with record id |
| Mendix (`mxui`, `mxclientsystem`) | none — deeplink | Brighton is the reference case |
## Not ported

### Already covered by HACS scrapers
- Teignbridge (`hacs_teignbridge_gov_uk.py`)
- Basildon (`hacs_basildon_gov_uk.py`)

### Decided since (see triage rule above)
- **Powys** — ported as `port_powys_council.py` (GOSS Forms, plain HTTP).
- **MidSuffolk** — ported as `port_mid_suffolk_district_council.py` (Placecube POST, plain HTTP); Babergh likewise.
- **ForestOfDean** — covered by restored `hacs_forest_of_dean_gov_uk.py`.
- **Brighton** (Mendix) — confirmed deeplink, the reference case.
- **Sevenoaks** (Oncreate-family) — port candidate, not ruled out: token replay, no captcha seen. Hertsmere ported as `port_hertsmere_borough_council.py` (same family, but a search-widget flow rather than Sevenoaks' `handle_event` + minted-URL flow).
- **StaffsMoorlands** (`bins.*` PublicDashboard SPA) — undecided, needs one more probe for the dashboard data endpoint.

### Too complex for plain HTTP (original assessment, kept for context)
- **StaffsMoorlands, Powys** (Jadu CXM) — client-side Handlebars rendering, session-dependent form tokens
- **Sevenoaks, Hertsmere** (Jadu Continuum) — encrypted typeahead params, version-specific page IDs
- **MidSuffolk** (Liferay) — React form-context-provider API
- **ForestOfDean** (Salesforce Aura) — multi-step flow with session tokens
- **Brighton** (Mendix) — session-specific GUIDs

### iTouchVision (recommend HACS reuse)
- **BlaenauGwent, EpsomAndEwell, Hyndburn, Winchester, Somerset, TestValley** — AES-encrypted responses

## Testing

These are draft ports. Each needs live testing:
```bash
# From project root, test a specific port:
cd /path/to/project
python3 -c "
import asyncio
from scripts.ukbcd_selenium_port.ports.tendring_district_council import Source
s = Source(uprn='100090604247')
print(asyncio.run(s.fetch()))
"
```
