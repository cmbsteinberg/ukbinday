# UK Bin Collection API

A FastAPI service that returns bin and waste collection schedules for UK councils. It wraps about 350 council scrapers from two upstream open-source projects and exposes them as a single async API.

## How It Works

Each UK council publishes bin collection dates on its own website in its own format. Two community projects have built scrapers for these sites: [hacs_waste_collection_schedule](https://github.com/mampfes/hacs_waste_collection_schedule) (primarily for Home Assistant) and [UKBinCollectionData](https://github.com/robbrad/UKBinCollectionData). This project takes those scrapers, patches them to run as async Python (converting `requests` to `httpx` via AST transforms), and serves them behind a FastAPI application.

The API resolves a postcode to addresses (with UPRNs), identifies the correct council scraper, and returns upcoming collection dates. It also provides an iCal endpoint for calendar subscriptions and a coverage map showing which councils are supported.

Scraper sync and patching is handled by scripts in `pipeline/`. HACS scrapers (about 240) are the primary source. UKBinCollectionData scrapers (about 110) fill in gaps where HACS has no coverage or where the HACS scraper is broken.

## Setup

Requires Python 3.13+ and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/09steicm/bins.git
cd bins
uv sync
```

To start the development server:

```bash
uv run uvicorn api.main:app --reload
```

The app will be available at `http://localhost:8000`. API docs are at `/api/v1/docs`.

### Optional: Redis

If you want rate limiting and request coalescing, run Redis locally or set the `REDIS_URL` environment variable. Without it, rate limiting is simply disabled and the API works fine.

### Linting

```bash
uv run ruff check --fix          # Python (excludes scrapers)
npx @biomejs/biome check --write  # JS/JSON
```

### Pre-commit Hooks

The project uses [lefthook](https://github.com/evilmartians/lefthook) for pre-commit hooks that run linting, smoke tests, and scraper sync checks.

## Tests

```bash
uv run pytest tests/test_ci.py -v          # Fast smoke tests (~1s)
uv run pytest tests/test_frontend.py -v    # API surface tests (~1s)
uv run pytest tests/test_integration.py -v # Live integration tests (~40s)
uv run pytest tests/test_deploy.py -v      # Docker stack tests (~60s)
```

The smoke tests (`test_ci.py`) verify that all scrapers parse, import, and register correctly. The integration tests hit live council websites and take longer.

## Syncing Scrapers

To pull the latest scrapers from upstream and patch them:

```bash
pipeline/hacs/sync.sh    # Primary source (HACS)
pipeline/ukbcd/sync.sh   # Fallback source (UKBinCollectionData)
```

After syncing, regenerate test cases and lookup data:

```bash
uv run python -m pipeline.hacs.generate_test_lookup
uv run python -m pipeline.ukbcd.generate_test_lookup
uv run python -m scripts.generate_admin_lookup
```

## Deployment

The project deploys as a Docker Compose stack (API + Redis + Caddy + Uptime Kuma) to a Hetzner VPS. Caddy handles TLS certificates automatically.

```bash
docker compose up --build
```

For full deployment instructions, including automated Hetzner provisioning, see [deploy/deployment.md](deploy/deployment.md).
