# UKBCD Selenium Scraper Ports

Draft ports of UKBCD selenium scrapers to plain `httpx` + `BeautifulSoup`.
Each file follows the HACS scraper pattern (`Source` class, `TITLE`, `URL`, `TEST_CASES`, `async fetch()`).

## Ported (14 councils)

### Browserless (no XHR traffic — upstream never used the browser for data)
| File | Council | Notes |
|------|---------|-------|
| `dumfries_and_galloway_council.py` | Dumfries & Galloway | Downloads ICS calendar by UPRN |
| `edinburgh_city_council.py` | City of Edinburgh | Pure calculation from rota anchors; takes `house_number`=day, `postcode`=week |

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
| `northumberland_council.py` | Northumberland | CSRF form (postcode → UPRN → HTML table) |
| `torbay_council.py` | Torbay | ServiceBuilder form (renderform + UPRN → HTML) |
| `wychavon_district_council.py` | Wychavon | Address lookup API + form POST → HTML table |
| `new_forest_council.py` | New Forest | Oracle eBase/UFS form (postcode → UPRN → JSON) |
| `ceredigion_county_council.py` | Ceredigion | Oracle eBase/UFS form (postcode → address → results page) |
| `mid_ulster_district_council.py` | Mid Ulster | Azure REST API (`/api/addresses` + `/api/collectiondates`) |
| `hillingdon_council.py` | Hillingdon | Jadu CXM JSON-RPC (`/apiserver/ajaxlibrary`) — returns day name + bin types |
## Not ported

### Already covered by HACS scrapers
- Teignbridge (`hacs_teignbridge_gov_uk.py`)
- Basildon (`hacs_basildon_gov_uk.py`)

### Too complex for plain HTTP
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
