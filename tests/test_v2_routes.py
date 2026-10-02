"""
The v2 routes (/api/v2/{lad}/find|view|subscribe|download), shaped after the
LocalGov Drupal waste collection module: the mapped schedule shape, LAD codes
and old scraper IDs in the path, deeplinks, error mapping as v1, the ICS
endpoints, and the address list.

Module `fetch` methods and the address API are stubbed per test; no network.

Usage:
    uv run pytest tests/test_v2_routes.py -v
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

from api.councils._base import (
    AddressNotFound,
    Collection,
    Icon,
    InputError,
    NeedsBrowser,
    UpstreamError,
)
from api.councils._base.discovery import load
from api.main import app
from api.services import address_lookup, scraper_registry
from api.services.bank_holidays import holiday_name

pytestmark = pytest.mark.api

LAD_LOOKUP = json.loads((Path(__file__).resolve().parent.parent / "api" / "data" / "lad_lookup.json").read_text())

HARTLEPOOL = "E06000001"  # module hartlepool
HARTLEPOOL_OLD = "hacs_hartlepool_gov_uk"
COVENTRY = "E08000026"  # module coventry sets needs_browser
UNWIRED = "E07000119"  # Fylde, deliberately unwired

_uprns = itertools.count(900000500001)


def fresh_uprn() -> str:
    return str(next(_uprns))


def soon(days: int = 3) -> datetime.date:
    return datetime.date.today() + datetime.timedelta(days=days)


def next_holiday(lad: str) -> tuple[datetime.date, str]:
    day = datetime.date.today() + datetime.timedelta(days=1)
    for _ in range(400):
        if name := holiday_name(lad, day):
            return day, name
        day += datetime.timedelta(days=1)
    raise AssertionError("no bank holiday in the next 400 days")


@pytest_asyncio.fixture(scope="module", loop_scope="session")
async def client():
    async with LifespanManager(app) as manager:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=manager.app),
            base_url="http://testserver/api",
        ) as c:
            yield c


@pytest.fixture
def stub(monkeypatch):
    """stub(module, behaviour): an exception to raise or collections to return."""

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


# --- view ---------------------------------------------------------------------


@pytest.mark.asyncio(loop_scope="session")
async def test_view_maps_collections_to_dates(client, stub):
    holiday, holiday_title = next_holiday(HARTLEPOOL)
    plain = soon()
    while holiday_name(HARTLEPOOL, plain):
        plain += datetime.timedelta(days=1)
    calls = stub(
        "hartlepool",
        [
            Collection(holiday, "Recycling (Blue Bin)"),
            Collection(plain, "Green waste"),
            Collection(plain, "Black bin"),
        ],
    )
    uprn = fresh_uprn()
    r = await client.get(f"/v2/{HARTLEPOOL}/view/{uprn}", params={"postcode": "TS26 0BL"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) == {"uprn", "council", "cached", "cached_at", "dates", "deeplink"}
    assert (body["uprn"], body["council"], body["cached"], body["deeplink"]) == (uprn, HARTLEPOOL, False, None)
    assert calls[0].uprn == uprn and calls[0].postcode == "TS26 0BL"

    dates = body["dates"]
    assert [d["date"] for d in dates] == sorted(d["date"] for d in dates)  # ascending, ISO
    by_label = {d["type"]["label"]: d for d in dates}
    assert by_label["Recycling (Blue Bin)"]["date"] == holiday.isoformat()
    assert by_label["Recycling (Blue Bin)"]["holiday"] == holiday_title
    assert by_label["Recycling (Blue Bin)"]["type"]["colour"] == "Blue"
    assert by_label["Recycling (Blue Bin)"]["type"]["icon"] == Icon.RECYCLING
    assert by_label["Black bin"]["type"]["colour"] == "Black"
    assert by_label["Green waste"]["type"]["colour"] is None  # the stream, not a bin colour
    assert by_label["Black bin"]["holiday"] is None
    assert "weekly_collection" not in body and "collection_time" not in body

    again = await client.get(f"/v2/{HARTLEPOOL}/view/{uprn}")
    assert again.json()["cached"] and again.json()["dates"] == dates


@pytest.mark.asyncio(loop_scope="session")
async def test_view_matches_v1_lookup(client, stub):
    stub("hartlepool", [Collection(soon(5), "Refuse"), Collection(soon(2), "Recycling")])
    uprn = fresh_uprn()
    v1 = (await client.get(f"/v1/lookup/{uprn}", params={"council": HARTLEPOOL})).json()
    v2 = (await client.get(f"/v2/{HARTLEPOOL}/view/{uprn}")).json()
    assert [(c["date"], c["type"], c["icon"]) for c in v1["collections"]] == [
        (d["date"], d["type"]["label"], d["type"]["icon"]) for d in v2["dates"]
    ]


@pytest.mark.asyncio(loop_scope="session")
async def test_old_scraper_id_in_path_resolves(client, stub):
    calls = stub("hartlepool", [Collection(soon(), "Refuse")])
    uprn = fresh_uprn()
    r = await client.get(f"/v2/{HARTLEPOOL_OLD}/view/{uprn}")
    assert r.status_code == 200, r.text
    assert r.json()["council"] == HARTLEPOOL
    assert len(calls) == 1
    assert (await app.state.ics_cache.read(uprn)).scraper == HARTLEPOOL


@pytest.mark.asyncio(loop_scope="session")
async def test_address_only_uprn_is_not_cached(client, stub):
    """An address-only council (UPRN 0) scrapes live every time, as v1."""
    cotswold = load("cotswold").meta.lads[0]
    calls = stub("cotswold", [Collection(soon(), "Refuse")])
    for _ in range(2):
        r = await client.get(f"/v2/{cotswold}/view/0", params={"address": "1 High St"})
        assert r.status_code == 200, r.text
    assert len(calls) == 2
    assert r.json()["cached"] is False and [d["type"]["label"] for d in r.json()["dates"]] == ["Refuse"]


@pytest.mark.asyncio(loop_scope="session")
async def test_unknown_council_is_404(client):
    assert (await client.get(f"/v2/hacs_no_such_council/view/{fresh_uprn()}")).status_code == 404
    assert (await client.get("/v2/hacs_no_such_council/find", params={"postcode": "TS26 0BL"})).status_code == 404


# --- deeplinks ------------------------------------------------------------------


@pytest.mark.asyncio(loop_scope="session")
async def test_unwired_council_gives_deeplink(client):
    r = await client.get(f"/v2/{UNWIRED}/view/{fresh_uprn()}")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["council"] == UNWIRED and body["dates"] == []
    assert body["deeplink"]["url"]
    sub = await client.get(f"/v2/{UNWIRED}/subscribe/{fresh_uprn()}", follow_redirects=False)
    assert sub.status_code == 302 and sub.headers["location"] == body["deeplink"]["url"]


@pytest.mark.asyncio(loop_scope="session")
async def test_needs_browser_gives_deeplink(client):
    coventry = load("coventry")
    r = await client.get(f"/v2/{COVENTRY}/view/100070713054", params={"postcode": "CV3 2LS", "house_number": "6"})
    assert r.status_code == 200, r.text
    assert r.json()["dates"] == []
    assert r.json()["deeplink"] == {
        "url": coventry.meta.url,
        "reason": coventry.needs_browser,
        "council_name": coventry.meta.title,
    }
    for kind in ("subscribe", "download"):
        cal = await client.get(f"/v2/{COVENTRY}/{kind}/100070713054", follow_redirects=False)
        assert cal.status_code == 404 and coventry.needs_browser in cal.json()["detail"]


@pytest.mark.asyncio(loop_scope="session")
async def test_needs_browser_raised_mid_fetch(client, stub):
    stub("hartlepool", NeedsBrowser("Blocked by a Cloudflare challenge."))
    r = await client.get(f"/v2/{HARTLEPOOL}/view/{fresh_uprn()}")
    assert r.status_code == 200
    assert r.json()["deeplink"]["reason"] == "Blocked by a Cloudflare challenge."


@pytest.mark.asyncio(loop_scope="session")
async def test_upstream_failure_gives_deeplink_and_header(client, stub):
    stub("hartlepool", UpstreamError("HTTP 502 from the council"))
    r = await client.get(f"/v2/{HARTLEPOOL}/view/{fresh_uprn()}")
    assert r.status_code == 200
    assert r.headers["X-Scrape-Failure"] == "network"
    assert r.json()["dates"] == []
    assert r.json()["deeplink"]["url"] == LAD_LOOKUP[HARTLEPOOL]["govuk_url"]


@pytest.mark.asyncio(loop_scope="session")
async def test_timeout_gives_deeplink_and_header(client, monkeypatch):
    async def slow(address, http):
        await asyncio.sleep(5)
        return []

    monkeypatch.setattr(scraper_registry, "SCRAPER_TIMEOUT", 0.05)
    monkeypatch.setattr(load("hartlepool"), "fetch", slow)
    r = await client.get(f"/v2/{HARTLEPOOL}/view/{fresh_uprn()}")
    assert r.status_code == 200
    assert r.headers["X-Scrape-Failure"] == "timeout"


# --- error mapping, as v1 -----------------------------------------------------------


@pytest.mark.asyncio(loop_scope="session")
@pytest.mark.parametrize(
    ("exc", "status", "detail"),
    [
        (InputError("unknown UPRN"), 422, "don't match"),
        (AddressNotFound("no match", ["1 High Street"]), 422, "don't match"),
        (KeyError("results"), 503, "Something went wrong"),
    ],
)
async def test_view_error_mapping_matches_v1(client, stub, exc, status, detail):
    stub("hartlepool", exc)
    v2 = await client.get(f"/v2/{HARTLEPOOL}/view/{fresh_uprn()}")
    v1 = await client.get(f"/v1/lookup/{fresh_uprn()}", params={"council": HARTLEPOOL})
    assert v2.status_code == v1.status_code == status
    assert v2.json() == v1.json() and detail in v2.json()["detail"]


@pytest.mark.asyncio(loop_scope="session")
async def test_calendar_error_mapping_matches_v1(client, stub, monkeypatch):
    stub("hartlepool", UpstreamError("down"))
    for path in (f"/v2/{HARTLEPOOL}/subscribe/{fresh_uprn()}", f"/v2/{HARTLEPOOL}/download/{fresh_uprn()}"):
        r = await client.get(path)
        assert r.status_code == 503 and "couldn't reach" in r.json()["detail"]

    async def slow(address, http):
        await asyncio.sleep(5)
        return []

    monkeypatch.setattr(scraper_registry, "SCRAPER_TIMEOUT", 0.05)
    monkeypatch.setattr(load("hartlepool"), "fetch", slow)
    r = await client.get(f"/v2/{HARTLEPOOL}/subscribe/{fresh_uprn()}")
    assert r.status_code == 504


@pytest.mark.asyncio(loop_scope="session")
async def test_missing_required_param_is_422(client):
    r = await client.get(f"/v2/{HARTLEPOOL}/view/0")
    assert r.status_code == 422


@pytest.mark.asyncio(loop_scope="session")
async def test_calendar_needs_a_real_uprn(client):
    r = await client.get(f"/v2/{HARTLEPOOL}/subscribe/0", params={"postcode": "TS26 0BL"})
    assert r.status_code == 422


# --- subscribe / download ------------------------------------------------------------


@pytest.mark.asyncio(loop_scope="session")
async def test_subscribe_and_download_serve_the_ics(client, stub):
    stub("hartlepool", [Collection(soon(), "Refuse")])
    uprn = fresh_uprn()
    sub = await client.get(f"/v2/{HARTLEPOOL_OLD}/subscribe/{uprn}")
    assert sub.status_code == 200, sub.text
    assert sub.headers["content-type"].startswith("text/calendar")
    assert "content-disposition" not in sub.headers
    assert b"BEGIN:VCALENDAR" in sub.content and b"SUMMARY:Refuse" in sub.content

    dl = await client.get(f"/v2/{HARTLEPOOL}/download/{uprn}")
    assert dl.status_code == 200
    assert dl.headers["content-disposition"] == f'attachment; filename="bins-{uprn}.ics"'
    v1 = await client.get(f"/v1/calendar/{uprn}", params={"council": HARTLEPOOL})
    assert dl.content == sub.content == v1.content
    assert dl.headers["content-disposition"] == v1.headers["content-disposition"]


# --- find ---------------------------------------------------------------------------


@pytest.mark.asyncio(loop_scope="session")
async def test_find_returns_addresses(client, monkeypatch):
    seen = []

    async def search(postcode):
        seen.append(postcode)
        return [
            {
                "uprn": "100110000001",
                "full_address": "1 High Street, Hartlepool, TS26 0BL",
                "postcode": "TS26 0BL",
                "address_line_1": "1 High Street",
                "house_number_or_name": "1",
                "street": "High Street",
            }
        ]

    monkeypatch.setattr(address_lookup, "search_addresses", search)
    r = await client.get(f"/v2/{HARTLEPOOL_OLD}/find", params={"postcode": "ts26 0bl"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["council"] == HARTLEPOOL and body["postcode"] == "TS26 0BL"
    assert [a["uprn"] for a in body["addresses"]] == ["100110000001"]
    assert body["addresses"][0]["street"] == "High Street"
    assert seen == ["ts26 0bl"]

    unwired = await client.get(f"/v2/{UNWIRED}/find", params={"postcode": "FY8 1AA"})
    assert unwired.status_code == 200 and unwired.json()["council"] == UNWIRED


@pytest.mark.asyncio(loop_scope="session")
async def test_find_address_api_failure_is_503(client, monkeypatch):
    async def broken(postcode):
        raise httpx.HTTPStatusError("boom", request=httpx.Request("GET", "http://x"), response=httpx.Response(500))

    monkeypatch.setattr(address_lookup, "search_addresses", broken)
    r = await client.get(f"/v2/{HARTLEPOOL}/find", params={"postcode": "TS26 0BL"})
    assert r.status_code == 503


@pytest.mark.asyncio(loop_scope="session")
async def test_find_needs_a_postcode(client):
    assert (await client.get(f"/v2/{HARTLEPOOL}/find")).status_code == 422


# --- schema -------------------------------------------------------------------------


@pytest.mark.asyncio(loop_scope="session")
async def test_v2_is_in_the_openapi_schema(client):
    paths = (await client.get("/v1/openapi.json")).json()["paths"]
    for route in ("find", "view/{uprn}", "subscribe/{uprn}", "download/{uprn}"):
        assert f"/api/v2/{{lad}}/{route}" in paths
    assert "/api/v1/lookup/{uprn}" in paths and "/api/v1/calendar/{uprn}" in paths
