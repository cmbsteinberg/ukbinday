"""
ICS cache keying: address-only lookups (/{lad}/view/0) must not share a cache
entry, and a cached entry from one scraper must not answer for another.

Scrapers are stubbed; no network.

Usage:
    uv run pytest tests/test_scrape_cache.py -v
"""

import datetime

import httpx
import pytest
import pytest_asyncio
from asgi_lifespan import LifespanManager

from api.councils._base import Collection
from api.main import app
from api.services.scrape_orchestrator import is_cacheable_uprn

pytestmark = pytest.mark.api

A = "E07000008"  # Cambridge
B = "E08000001"  # Bolton


@pytest_asyncio.fixture(scope="module", loop_scope="session")
async def client():
    async with LifespanManager(app) as manager:
        registry = app.state.registry
        calls: list[tuple[str, dict]] = []

        async def fake_invoke(council_id, params):
            calls.append((council_id, dict(params)))
            # Encode the input in the bin type so responses are distinguishable
            label = f"{council_id}:{params.get('house_number', '')}"
            return [Collection(datetime.date.today() + datetime.timedelta(days=3), label)]

        original = registry.invoke
        registry.invoke = fake_invoke
        try:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=manager.app),
                base_url="http://testserver/api/v2",
            ) as c:
                c.calls = calls
                yield c
        finally:
            registry.invoke = original


def test_is_cacheable_uprn():
    assert is_cacheable_uprn("100023336956")
    assert is_cacheable_uprn("000151124612")
    assert not is_cacheable_uprn("0")
    assert not is_cacheable_uprn("000")
    assert not is_cacheable_uprn("")
    assert not is_cacheable_uprn("abc")


@pytest.mark.asyncio(loop_scope="session")
async def test_address_only_lookups_do_not_share_cache(client):
    q = {"postcode": "CB1 1AA"}
    r1 = await client.get(f"/{A}/view/0", params={**q, "house_number": "1"})
    r2 = await client.get(f"/{A}/view/0", params={**q, "house_number": "2"})
    assert r1.status_code == r2.status_code == 200
    assert r1.json()["dates"][0]["type"]["label"] == f"{A}:1"
    assert r2.json()["dates"][0]["type"]["label"] == f"{A}:2"
    assert not r2.json()["cached"]


@pytest.mark.asyncio(loop_scope="session")
async def test_cache_entry_not_reused_across_scrapers(client):
    uprn = "999000111222"
    params = {"postcode": "BL1 1AA", "house_number": "5"}
    ra = await client.get(f"/{A}/view/{uprn}", params=params)
    rb = await client.get(f"/{B}/view/{uprn}", params=params)
    assert ra.json()["dates"][0]["type"]["label"].startswith(A)
    assert rb.json()["dates"][0]["type"]["label"].startswith(B)
    assert not rb.json()["cached"]
    # Same scraper + same UPRN is a legitimate hit
    ra2 = await client.get(f"/{B}/view/{uprn}", params=params)
    assert ra2.json()["cached"]


@pytest.mark.asyncio(loop_scope="session")
async def test_calendar_rejects_placeholder_uprn(client):
    for kind in ("subscribe", "download"):
        r = await client.get(f"/{A}/{kind}/0", params={"postcode": "CB1 1AA", "house_number": "1"})
        assert r.status_code == 422
