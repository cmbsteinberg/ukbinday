# UK Bin Collection API

![councils with bin dates](https://img.shields.io/endpoint?url=https%3A%2F%2Fraw.githubusercontent.com%2F09steicm%2Fbins%2Fmain%2Fbadge_coverage.json)

An API that tells you when your bins are being collected. Enter a postcode, pick your address, get your collection dates back as JSON or subscribe via iCal.

Under the hood, it pulls from about 350 council scrapers maintained by two community projects — [hacs_waste_collection_schedule](https://github.com/mampfes/hacs_waste_collection_schedule) and [UKBinCollectionData](https://github.com/robbrad/UKBinCollectionData) — patches them to run as async Python, and serves them through a single FastAPI app.

## Coverage

<!-- coverage:start -->
```mermaid
---
config:
  sankey:
    width: 800
    height: 400
    linkColor: source
    nodeAlignment: left
---
sankey-beta

"Councils","Bin dates",343
"Councils","Deeplink (no scraper possible)",14
"Councils","Broken (being fixed)",4
```

Of 361 councils, 343 return bin dates. The other 18 send users to the council's own bin-day page:

**Deeplinked by design (14)**: the council's lookup can't be scraped.

| Council | Why |
|---|---|
| Brighton and Hove | Mendix platform, no plain-HTTP path (reference case) |
| Causeway Coast and Glens | no address lookup exists, only 4 area calendar PDFs with colour-only week marking and no address-to-area mapping |
| City of London | no address lookup feed exists, estate-based collections via Veolia with static pages only |
| Coventry | Coventry's bin-day search is behind a reCAPTCHA. |
| Derry City and Strabane | no address lookup exists, one generic calendar image; the Sentireal app backend is not publicly reachable |
| Fylde | Bartec portal behind mandatory login, no guest lookup (dead by redesign) |
| Halton | ASP.NET WebForms behind reCAPTCHA v2, server-side validator rejects guest POSTs with no data endpoint |
| Havant | Havant's bin days are only shown after logging in to a council account. |
| Isle of Wight | Blazor Server app (state over a SignalR WebSocket, no HTTP data endpoint) and bin types only as PDF cell colours that change yearly (2026-10-01) |
| Isles of Scilly | no address lookup exists, static round map + area table only (no kerbside off St Mary's/St Martins) |
| North East Derbyshire | Firmstep Check_your_Bin_Day retired (302, button commented out), static Calendar A/B only; apibroker 403 |
| Preston | Preston's bin-day search answers every automated request with an image captcha. |
| Rutland | bin lookup behind Salesforce MyAccount login wall, no guest flow |
| Southampton | whole domain behind Incapsula, 403 on all server-side fingerprints, no alternate API |

**Broken (4)**: a scraper exists but failed the last live run, usually because the council's site is down.

| Council | Last run |
|---|---|
| Ards and North Down | broken / upstream_error |
| Charnwood | broken / upstream_error |
| North Norfolk | unverified / unreachable |
| Telford and Wrekin | broken / upstream_error |
<!-- coverage:end -->

The [coverage map](https://ukbinday.co.uk/coverage) shows each council on a map.

## API

Base URL: `https://ukbinday.co.uk`

| Endpoint | Description |
|---|---|
| `GET /api/v1/addresses/{postcode}` | List addresses for a postcode (with UPRNs) |
| `GET /api/v1/lookup/{uprn}` | Get bin collection dates for a UPRN |
| `GET /api/v1/calendar/{uprn}` | iCal feed for calendar subscriptions |
| `GET /api/v1/council/{postcode}` | Identify which council covers a postcode |
| `GET /api/v1/councils` | List all supported councils |
| `GET /api/v1/health` | Health check |

Interactive docs at [`/api/v1/docs`](https://ukbinday.co.uk/api/v1/docs).

## Setup

Python 3.13+ and [uv](https://docs.astral.sh/uv/).

```bash
uv sync
uv run uvicorn api.main:app --reload
```

The app runs at `http://localhost:8000`.

Rate limiting needs Redis — set `REDIS_URL` or just leave it off and the API works without it.

## Tests

```bash
uv run pytest -m ci -v                    # smoke tests: syntax, imports, registry (~1s)
uv run pytest -m api -v                   # API routes, CORS, error cases (~1s)
uv run pytest -m live -v                  # every council against live sites (~7 min)
uv run pytest -m docker -v                # Docker compose stack (~60s)
uv run pytest -m "not live and not docker" -v  # all fast tests
```

The live test (`tests/test_lad_integration.py`) runs one test per council (LAD code), using real addresses sampled from ONS data and looked up the same way the frontend does. Run a few councils by LAD code:

```bash
LAD_CODES=S12000033,E08000035 uv run pytest tests/test_lad_integration.py -v
```

Test runs only write `tests/output/lad_integration_output.json`. To refresh the `working` flags, badge, sankey and coverage map from it, run `./pipeline/ci/post_integration.sh`.

## Syncing scrapers from upstream

The scrapers in `api/scrapers/` are patched copies of the upstream originals. The sync scripts clone each upstream repo, apply AST transforms (converting `requests` calls to async `httpx`), and drop the results into the scrapers directory.

```bash
pipeline/hacs/sync.sh    # primary source
pipeline/ukbcd/sync.sh   # fallback source
```

After syncing, regenerate the lookup data:

```bash
uv run python -m pipeline.hacs.generate_test_lookup
uv run python -m pipeline.ukbcd.generate_test_lookup
uv run python -m scripts.generate_admin_lookup
```

## Deployment

Docker Compose stack: API + Redis + Caddy (reverse proxy, auto TLS) + Uptime Kuma (monitoring).

```bash
docker compose up --build
```

See [deploy/deployment.md](deploy/deployment.md) for Hetzner provisioning and production setup.

## Linting

```bash
uv run ruff check --fix          # Python (scrapers excluded)
npx @biomejs/biome check --write  # JS/JSON
```

Pre-commit hooks via [lefthook](https://github.com/evilmartians/lefthook) run linting, smoke tests, and scraper sync checks automatically.

## Acknowledgements

This project wouldn't exist without the scraper collections built by [mampfes/hacs_waste_collection_schedule](https://github.com/mampfes/hacs_waste_collection_schedule) and [robbrad/UKBinCollectionData](https://github.com/robbrad/UKBinCollectionData). If your council isn't supported, consider contributing a scraper to one of those projects.
