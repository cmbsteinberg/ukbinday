"""
Lightweight CI smoke tests — no network calls, fast.

Checks that scripts parse, the app starts, and the registry serves every
wired LAD. Each council module's own load check is in tests/test_councils.py.

Usage:
    uv run pytest tests/test_ci.py -v
"""

import ast
import json
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from asgi_lifespan import LifespanManager

from api.main import app

pytestmark = pytest.mark.ci

ROOT = Path(__file__).resolve().parent.parent
LAD_LOOKUP = ROOT / "api" / "data" / "lad_lookup.json"

BASE_URL = "http://testserver"


# ---------------------------------------------------------------------------
# 1. Scripts parse as valid Python
# ---------------------------------------------------------------------------

SCRIPTS_DIR = ROOT / "scripts"
SCRIPT_FILES = sorted(
    p
    for p in SCRIPTS_DIR.rglob("*.py")
    if p.name != "__init__.py" and "__pycache__" not in str(p)
)


@pytest.mark.parametrize(
    "path",
    SCRIPT_FILES,
    ids=[p.name for p in SCRIPT_FILES],
)
def test_script_parses(path: Path):
    """Each script file must be valid Python syntax."""
    source = path.read_text()
    ast.parse(source, filename=str(path))


# ---------------------------------------------------------------------------
# 2. App starts and the registry serves every wired LAD
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture(scope="module", loop_scope="session")
async def client():
    async with LifespanManager(app) as manager:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=manager.app), base_url=BASE_URL
        ) as c:
            yield c


@pytest.mark.asyncio(loop_scope="session")
async def test_app_starts(client):
    """The app should start and respond to a basic request."""
    resp = await client.get("/")
    assert resp.status_code == 200


@pytest.mark.asyncio(loop_scope="session")
async def test_registry_loads_all_scrapers(client):
    """/councils lists exactly the wired LADs, each under its LAD code."""
    resp = await client.get("/api/v2/councils")
    assert resp.status_code == 200
    ids = {c["id"] for c in resp.json()}
    lad_lookup = json.loads(LAD_LOOKUP.read_text())
    wired = {code for code, v in lad_lookup.items() if v.get("scraper_id")}
    assert ids == wired, (
        f"missing: {sorted(wired - ids)}, not wired: {sorted(ids - wired)}"
    )


@pytest.mark.asyncio(loop_scope="session")
async def test_status_counts_every_scraper(client):
    councils_resp = await client.get("/api/v2/councils")
    status_resp = await client.get("/api/v2/status")
    assert status_resp.status_code == 200
    assert status_resp.json()["scraper_count"] == len(councils_resp.json())
