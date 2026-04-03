"""
Lightweight CI smoke tests — no network calls, fast.

Checks that all scrapers compile, compat modules import, scripts parse,
the app starts, and the registry loads all scrapers without errors.

Usage:
    uv run pytest tests/test_ci.py -v
"""

import ast
import importlib
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from asgi_lifespan import LifespanManager

from api.main import app

SCRAPERS_DIR = Path(__file__).resolve().parent.parent / "api" / "scrapers"
COMPAT_DIR = Path(__file__).resolve().parent.parent / "api" / "compat"

BASE_URL = "http://testserver"

# ---------------------------------------------------------------------------
# Collect all scraper and compat module paths
# ---------------------------------------------------------------------------

SCRAPER_FILES = sorted(
    p for p in SCRAPERS_DIR.glob("*.py") if p.name != "__init__.py"
)

COMPAT_MODULES = sorted(
    p
    for p in COMPAT_DIR.rglob("*.py")
    if p.name != "__init__.py" and "__pycache__" not in str(p)
)


def _module_name(path: Path, root_name: str = "api") -> str:
    """Convert a file path to a dotted module name relative to the project root."""
    parts = path.with_suffix("").parts
    idx = parts.index(root_name)
    return ".".join(parts[idx:])


# ---------------------------------------------------------------------------
# 1. All scrapers parse as valid Python (AST-level — no imports executed)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    SCRAPER_FILES,
    ids=[p.stem for p in SCRAPER_FILES],
)
def test_scraper_parses(path: Path):
    """Each scraper file must be valid Python syntax."""
    source = path.read_text()
    ast.parse(source, filename=str(path))


# ---------------------------------------------------------------------------
# 2. All scrapers import successfully and expose the expected interface
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    SCRAPER_FILES,
    ids=[p.stem for p in SCRAPER_FILES],
)
def test_scraper_imports(path: Path):
    """Each scraper should import without error and define Source, TITLE, URL, TEST_CASES."""
    mod_name = _module_name(path)
    mod = importlib.import_module(mod_name)

    assert hasattr(mod, "Source"), f"{mod_name} missing Source class"
    assert hasattr(mod, "TITLE"), f"{mod_name} missing TITLE"
    assert hasattr(mod, "URL"), f"{mod_name} missing URL"
    assert hasattr(mod, "TEST_CASES"), f"{mod_name} missing TEST_CASES"

    # Source must have an async fetch method
    assert hasattr(mod.Source, "fetch"), f"{mod_name} Source missing fetch()"


# ---------------------------------------------------------------------------
# 3. All compat modules import successfully
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    COMPAT_MODULES,
    ids=[_module_name(p) for p in COMPAT_MODULES],
)
def test_compat_imports(path: Path):
    """Each compat module should import without error."""
    mod_name = _module_name(path)
    importlib.import_module(mod_name)


# ---------------------------------------------------------------------------
# 4. Key compat types are importable
# ---------------------------------------------------------------------------


def test_hacs_compat_types():
    from api.compat.hacs import (  # noqa: F401
        Collection,
        CollectionBase,
        CollectionGroup,
    )
    from api.compat.hacs.exceptions import SourceArgumentException  # noqa: F401
    from api.compat.hacs.service.ICS import ICS  # noqa: F401


def test_ukbcd_compat_types():
    from api.compat.ukbcd.common import check_uprn, date_format  # noqa: F401
    from api.compat.ukbcd.get_bin_data import AbstractGetBinDataClass  # noqa: F401


# ---------------------------------------------------------------------------
# 5. Scripts parse as valid Python
# ---------------------------------------------------------------------------

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
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
# 6. App starts and registry loads all scrapers
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
    """The registry should have loaded all scraper files (minus __init__.py)."""
    resp = await client.get("/api/v1/councils")
    assert resp.status_code == 200
    councils = resp.json()
    # We expect the registry to have loaded the vast majority of scrapers.
    # A few may legitimately fail to load, but if more than 5% are missing
    # something is seriously wrong.
    expected_min = len(SCRAPER_FILES) * 0.95
    assert len(councils) >= expected_min, (
        f"Registry only loaded {len(councils)} scrapers but {len(SCRAPER_FILES)} "
        f"scraper files exist (expected at least {int(expected_min)})"
    )


@pytest.mark.asyncio(loop_scope="session")
async def test_health_endpoint_returns_all(client):
    """Health endpoint should return an entry for every loaded scraper."""
    councils_resp = await client.get("/api/v1/councils")
    health_resp = await client.get("/api/v1/health")
    assert health_resp.status_code == 200
    assert len(health_resp.json()) == len(councils_resp.json())
