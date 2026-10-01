"""
The council modules (api/councils/) wired into the registry and routes:
LAD-code IDs and the old scraper IDs that resolve to them, NeedsBrowser
deeplinks, the upstream-failure deeplink fallback, error mapping, and
refreshing ICS sidecars written under old scraper IDs.

Module `fetch` methods are stubbed per test; no network.

Usage:
    uv run pytest tests/test_council_wiring.py -v
"""

from __future__ import annotations

import asyncio
import datetime
import itertools
import json
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from asgi_lifespan import LifespanManager

from api.compat.hacs.exceptions import SourceArgumentException
from api.councils._base import (
    AddressNotFound,
    Collection,
    InputError,
    NeedsBrowser,
    UpstreamError,
)
from api.councils._base.discovery import load
from api.main import app
from api.services import scraper_registry
from api.services.ics_cache import IcsCache
from api.services.refresh_job import RefreshJob
from api.services.scrape_orchestrator import map_scrape_exception

pytestmark = pytest.mark.api

LAD_LOOKUP = json.loads((Path(__file__).resolve().parent.parent / "api" / "data" / "lad_lookup.json").read_text())

HARTLEPOOL = "E06000001"  # module hartlepool
HARTLEPOOL_OLD = "hacs_hartlepool_gov_uk"  # its scraper ID until the switch to LAD codes
BRISTOL = "E06000023"  # module bristol
BRISTOL_OLD = "ukbcd_bristol_city_council"  # wired to E06000023 two scrapers ago
COVENTRY = "E08000026"  # module coventry sets needs_browser
ADUR, WORTHING = "E07000223", "E07000229"  # one module, adur_and_worthing

_uprns = itertools.count(900000000001)


def fresh_uprn() -> str:
    """A UPRN no other test has cached."""
    return str(next(_uprns))


def soon(days: int = 3) -> datetime.date:
    return datetime.date.today() + datetime.timedelta(days=days)


@pytest_asyncio.fixture(scope="module", loop_scope="session")
async def client():
    async with LifespanManager(app) as manager:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=manager.app),
            base_url="http://testserver/api/v1",
        ) as c:
            yield c


@pytest.fixture
def stub(monkeypatch):
    """stub(module, behaviour): replace a council module's fetch for one test.

    behaviour is an exception to raise, or a list of collections to return.
    Returns the list of Address objects fetch was called with.
    """

    def install(module: str, behaviour):
        calls = []

        async def fetch(address, http):
            calls.append(address)
            if isinstance(behaviour, BaseException):
                raise behaviour
            return list(behaviour)

        monkeypatch.setattr(load(module), "fetch", fetch)
        return calls

    return install


# --- IDs and aliases ---------------------------------------------------------


@pytest.mark.asyncio(loop_scope="session")
@pytest.mark.parametrize("council", [HARTLEPOOL, HARTLEPOOL_OLD])
async def test_lad_code_and_old_id_reach_the_module(client, stub, council):
    calls = stub("hartlepool", [Collection(soon(), "Refuse")])
    uprn = fresh_uprn()
    r = await client.get(f"/lookup/{uprn}", params={"council": council, "postcode": "TS26 0BL"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["council"] == HARTLEPOOL  # the public ID, whatever name the request used
    assert [c["type"] for c in body["collections"]] == ["Refuse"]
    assert calls and calls[0].uprn == uprn and calls[0].postcode == "TS26 0BL"
    entry = await app.state.ics_cache.read(uprn)
    assert entry.scraper == HARTLEPOOL


@pytest.mark.asyncio(loop_scope="session")
async def test_council_lookup_returns_the_lad_code(client):
    r = await client.get("/council/TS26 0BL")
    assert r.status_code == 200, r.text
    assert r.json()["council_id"] == HARTLEPOOL


@pytest.mark.asyncio(loop_scope="session")
async def test_retired_scraper_id_reaches_the_module(client, stub):
    """An ID once wired to a LAD (still in old calendar URLs) runs today's module."""
    calls = stub("bristol", [Collection(soon(), "Recycling")])
    r = await client.get(f"/lookup/{fresh_uprn()}", params={"council": BRISTOL_OLD})
    assert r.status_code == 200, r.text
    assert len(calls) == 1
    registry = app.state.registry
    assert registry.get(BRISTOL_OLD).module == "bristol"
    assert registry.canonical_id(BRISTOL_OLD) == BRISTOL


@pytest.mark.asyncio(loop_scope="session")
async def test_unknown_council_is_404(client):
    r = await client.get(f"/lookup/{fresh_uprn()}", params={"council": "hacs_no_such_council"})
    assert r.status_code == 404


@pytest.mark.asyncio(loop_scope="session")
async def test_every_wired_lad_answers_to_its_code(client):
    registry = app.state.registry
    for code, entry in LAD_LOOKUP.items():
        if entry.get("scraper_id"):
            meta = registry.get(code)
            assert meta is not None and meta.id == code, f"{code} ({entry['name']}) not served under its code"


@pytest.mark.asyncio(loop_scope="session")
async def test_two_lad_module_answers_to_each_code(client, stub):
    """Adur & Worthing: one module, two councils, each with its own ID and GOV.UK page."""
    registry = app.state.registry
    adur, worthing = registry.get(ADUR), registry.get(WORTHING)
    assert adur.module == worthing.module == "adur_and_worthing"
    assert (adur.id, worthing.id) == (ADUR, WORTHING)
    assert (adur.govuk_url, worthing.govuk_url) == (LAD_LOOKUP[ADUR]["govuk_url"], LAD_LOOKUP[WORTHING]["govuk_url"])
    councils = {c["id"] for c in (await client.get("/councils")).json()}
    assert {ADUR, WORTHING} <= councils

    stub("adur_and_worthing", UpstreamError("down"))
    r = await client.get(f"/lookup/{fresh_uprn()}", params={"council": WORTHING})
    assert r.json()["council"] == WORTHING
    assert r.json()["deeplink"]["url"] == LAD_LOOKUP[WORTHING]["govuk_url"]


@pytest.mark.asyncio(loop_scope="session")
async def test_councils_metadata_comes_from_requires(client):
    councils = {c["id"]: c for c in (await client.get("/councils")).json()}
    assert councils[HARTLEPOOL]["params"] == ["uprn", "postcode", "address", "house_number", "street"]
    assert councils[HARTLEPOOL]["name"] == load("hartlepool").meta.title
    registry = app.state.registry
    cotswold = next(m for m in registry.list_all() if m.module == "cotswold")
    assert cotswold.required_params == ["address"]  # `label` is sent as `address`
    assert BRISTOL_OLD not in councils and HARTLEPOOL_OLD not in councils  # old IDs, not councils


# --- NeedsBrowser ---------------------------------------------------------------


@pytest.mark.asyncio(loop_scope="session")
async def test_needs_browser_module_answers_with_deeplink(client):
    coventry = load("coventry")
    r = await client.get(
        "/lookup/100070713054", params={"council": COVENTRY, "postcode": "CV3 2LS", "house_number": "6"}
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["collections"] == []
    assert body["deeplink"] == {
        "url": coventry.meta.url,
        "reason": coventry.needs_browser,
        "council_name": coventry.meta.title,
    }
    cal = await client.get("/calendar/100070713054", params={"council": COVENTRY}, follow_redirects=False)
    assert cal.status_code == 404 and coventry.needs_browser in cal.json()["detail"]


@pytest.mark.asyncio(loop_scope="session")
async def test_needs_browser_council_skips_the_address_step(client):
    r = await client.get("/council/CV3 2LS")
    assert r.status_code == 200
    body = r.json()
    assert body["council_id"] is None
    assert body["deeplink"]["url"] == load("coventry").meta.url


@pytest.mark.asyncio(loop_scope="session")
async def test_needs_browser_raised_mid_fetch(client, stub):
    stub("hartlepool", NeedsBrowser("Blocked by a Cloudflare challenge."))
    r = await client.get(f"/lookup/{fresh_uprn()}", params={"council": HARTLEPOOL})
    assert r.status_code == 200
    deeplink = r.json()["deeplink"]
    assert deeplink["reason"] == "Blocked by a Cloudflare challenge."
    assert deeplink["url"] == load("hartlepool").meta.url


# --- Upstream failure fallback ----------------------------------------------------


@pytest.mark.asyncio(loop_scope="session")
async def test_upstream_failure_without_cache_gives_govuk_deeplink(client, stub):
    stub("hartlepool", UpstreamError("HTTP 502 from the council"))
    r = await client.get(f"/lookup/{fresh_uprn()}", params={"council": HARTLEPOOL})
    assert r.status_code == 200
    assert r.headers["X-Scrape-Failure"] == "network"
    body = r.json()
    assert body["collections"] == []
    assert body["deeplink"]["url"] == LAD_LOOKUP["E06000001"]["govuk_url"]
    assert "isn't responding" in body["deeplink"]["reason"]


@pytest.mark.asyncio(loop_scope="session")
async def test_timeout_without_cache_gives_deeplink(client, monkeypatch):
    async def slow(address, http):
        await asyncio.sleep(5)
        return []

    monkeypatch.setattr(scraper_registry, "SCRAPER_TIMEOUT", 0.05)
    monkeypatch.setattr(load("hartlepool"), "fetch", slow)
    r = await client.get(f"/lookup/{fresh_uprn()}", params={"council": HARTLEPOOL})
    assert r.status_code == 200
    assert r.headers["X-Scrape-Failure"] == "timeout"
    assert r.json()["deeplink"]["url"] == LAD_LOOKUP["E06000001"]["govuk_url"]


@pytest.mark.asyncio(loop_scope="session")
async def test_upstream_failure_with_cache_serves_cache(client, stub):
    uprn = fresh_uprn()
    stub("hartlepool", [Collection(soon(), "Refuse")])
    first = await client.get(f"/lookup/{uprn}", params={"council": HARTLEPOOL})
    assert first.status_code == 200 and not first.json()["cached"]

    stub("hartlepool", UpstreamError("down"))
    again = await client.get(f"/lookup/{uprn}", params={"council": HARTLEPOOL})
    assert again.status_code == 200
    assert again.json()["cached"] and again.json()["deeplink"] is None
    assert [c["type"] for c in again.json()["collections"]] == ["Refuse"]


@pytest.mark.asyncio(loop_scope="session")
async def test_calendar_keeps_503_on_upstream_failure(client, stub):
    stub("hartlepool", UpstreamError("down"))
    r = await client.get(f"/calendar/{fresh_uprn()}", params={"council": HARTLEPOOL})
    assert r.status_code == 503
    assert "couldn't reach" in r.json()["detail"]


@pytest.mark.asyncio(loop_scope="session")
async def test_module_bug_is_not_a_site_failure(client, stub):
    """Anything other than UpstreamError escaping a module is our bug: no deeplink."""
    stub("hartlepool", KeyError("results"))
    r = await client.get(f"/lookup/{fresh_uprn()}", params={"council": HARTLEPOOL})
    assert r.status_code == 503
    assert "Something went wrong" in r.json()["detail"]


# --- Error mapping ---------------------------------------------------------------


@pytest.mark.asyncio(loop_scope="session")
async def test_input_error_stays_422(client, stub):
    stub("hartlepool", InputError("unknown UPRN"))
    r = await client.get(f"/lookup/{fresh_uprn()}", params={"council": HARTLEPOOL})
    assert r.status_code == 422
    assert "suggestions" not in r.json()


@pytest.mark.asyncio(loop_scope="session")
async def test_address_not_found_is_422_with_suggestions(client, stub):
    stub("hartlepool", AddressNotFound("no match", ["1 High Street", "2 High Street"]))
    r = await client.get(f"/lookup/{fresh_uprn()}", params={"council": HARTLEPOOL})
    assert r.status_code == 422
    assert r.json()["suggestions"] == ["1 High Street", "2 High Street"]
    assert "don't match" in r.json()["detail"]


@pytest.mark.asyncio(loop_scope="session")
async def test_missing_required_param_is_422(client):
    r = await client.get("/lookup/0", params={"council": HARTLEPOOL})
    assert r.status_code == 422


@pytest.mark.parametrize(
    ("exc", "status"),
    [
        (InputError("x"), 422),
        (AddressNotFound("x"), 422),
        (UpstreamError("x"), 503),
        (SourceArgumentException("uprn", "bad"), 422),
        (httpx.ConnectError("x"), 503),
        (scraper_registry.ScraperTimeoutError("x"), 504),
        (ValueError("x"), 503),
    ],
)
def test_map_scrape_exception(exc, status):
    assert map_scrape_exception("c", exc).status_code == status


# --- Refresh of sidecars written under old IDs ---------------------------------------


@pytest.mark.asyncio(loop_scope="session")
async def test_sidecar_with_old_scraper_id_still_refreshes(client, stub, tmp_path):
    # Its own cache dir: run_once refreshes every eligible sidecar, and other
    # tests' failure sidecars would go to the network.
    registry = app.state.registry
    cache = IcsCache(tmp_path, canonical_id=registry.canonical_id)
    uprn = fresh_uprn()
    params = {"uprn": uprn, "postcode": "BS14 8ES"}
    # A sidecar as the old scraper left it: retired ID, no upcoming collections
    await cache.write(uprn, BRISTOL_OLD, params, [])
    calls = stub("bristol", [Collection(soon(), "Recycling")])

    stats = await RefreshJob(cache, registry).run_once()
    assert (stats.refreshed, stats.failed) == (1, 0)
    assert calls and calls[-1].uprn == uprn

    entry = await cache.read(uprn)
    assert entry.scraper == BRISTOL  # migrated to the LAD code
    assert entry.params == params
    assert [c["type"] for c in entry.collections] == ["Recycling"]


@pytest.mark.asyncio(loop_scope="session")
async def test_sidecar_with_unknown_id_fails_without_crashing(tmp_path):
    """A sidecar no council answers to (a removed scraper) counts as a failure and ages out."""
    cache = IcsCache(tmp_path, canonical_id=app.state.registry.canonical_id)
    uprn = fresh_uprn()
    await cache.write(uprn, "hacs_no_such_council", {"uprn": uprn}, [])
    job = RefreshJob(cache, app.state.registry, failure_threshold=2)

    assert (await job.run_once()).failed == 1
    assert (await cache.read(uprn)).consecutive_failures == 1
    assert (await job.run_once()).deleted == 1
    assert await cache.read(uprn) is None


@pytest.mark.asyncio(loop_scope="session")
async def test_cache_hit_across_alias(client, stub):
    """A sidecar under an alias answers a request under the current ID, and vice versa."""
    cache = app.state.ics_cache
    uprn = fresh_uprn()
    await cache.write(uprn, BRISTOL_OLD, {"uprn": uprn}, [Collection(soon(), "Refuse")])
    calls = stub("bristol", UpstreamError("should not be called"))
    r = await client.get(f"/lookup/{uprn}", params={"council": "E06000023"})
    assert r.status_code == 200 and r.json()["cached"]
    assert calls == []
