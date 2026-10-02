"""
The schedule routes (/api/v2/find, /api/v2/{lad}/view|subscribe|download),
shaped after the LocalGov Drupal waste collection module: the mapped schedule
shape, LAD codes and old scraper IDs in the path, deeplinks, error mapping,
the ICS endpoints, and the postcode's council and address list.

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

from api import config
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
UNWIRED_POSTCODE = "PR4 0YA"

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
    """An address-only council (UPRN 0) scrapes live every time."""
    cotswold = load("cotswold").meta.lads[0]
    calls = stub("cotswold", [Collection(soon(), "Refuse")])
    for _ in range(2):
        r = await client.get(f"/v2/{cotswold}/view/0", params={"address": "1 High St"})
        assert r.status_code == 200, r.text
    assert len(calls) == 2
    assert r.json()["cached"] is False and [d["type"]["label"] for d in r.json()["dates"]] == ["Refuse"]


@pytest.mark.asyncio(loop_scope="session")
async def test_unknown_council_is_404(client):
    for kind in ("view", "subscribe", "download"):
        r = await client.get(f"/v2/hacs_no_such_council/{kind}/{fresh_uprn()}")
        assert r.status_code == 404 and "/api/v2/councils" in r.json()["detail"]


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


# --- error mapping -----------------------------------------------------------------


@pytest.mark.asyncio(loop_scope="session")
@pytest.mark.parametrize(
    ("exc", "status", "detail"),
    [
        (InputError("unknown UPRN"), 422, "don't match"),
        (AddressNotFound("no match", ["1 High Street"]), 422, "don't match"),
        (KeyError("results"), 503, "Something went wrong"),
    ],
)
async def test_view_error_mapping(client, stub, exc, status, detail):
    stub("hartlepool", exc)
    r = await client.get(f"/v2/{HARTLEPOOL}/view/{fresh_uprn()}")
    assert r.status_code == status
    assert detail in r.json()["detail"]
    assert r.json().get("suggestions") == (list(exc.suggestions) if isinstance(exc, AddressNotFound) else None)


@pytest.mark.asyncio(loop_scope="session")
async def test_calendar_error_mapping(client, stub, monkeypatch):
    stub("hartlepool", UpstreamError("down"))
    for path in (f"/v2/{HARTLEPOOL}/subscribe/{fresh_uprn()}", f"/v2/{HARTLEPOOL}/download/{fresh_uprn()}"):
        r = await client.get(path)
        assert r.status_code == 503 and "couldn't reach" in r.json()["detail"]
        assert r.headers["cache-control"] == "no-store"  # never pinned by the edge cache

    async def slow(address, http):
        await asyncio.sleep(5)
        return []

    monkeypatch.setattr(scraper_registry, "SCRAPER_TIMEOUT", 0.05)
    monkeypatch.setattr(load("hartlepool"), "fetch", slow)
    r = await client.get(f"/v2/{HARTLEPOOL}/subscribe/{fresh_uprn()}")
    assert r.status_code == 504
    assert r.headers["cache-control"] == "no-store"


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
    assert dl.content == sub.content


@pytest.mark.asyncio(loop_scope="session")
async def test_v1_calendar_subscriptions_still_serve_the_feed(client, stub):
    # Pre-v2 subscriptions carry /api/v1/calendar/{uprn}?council=<LAD or old ID>
    stub("hartlepool", [Collection(soon(), "Refuse")])
    uprn = fresh_uprn()
    sub = await client.get(f"/v2/{HARTLEPOOL}/subscribe/{uprn}")
    for council in (HARTLEPOOL, HARTLEPOOL_OLD):
        old = await client.get(f"/v1/calendar/{uprn}", params={"council": council})
        assert old.status_code == 200, old.text
        assert old.headers["content-type"].startswith("text/calendar")
        assert old.content == sub.content


# --- find ---------------------------------------------------------------------------

ADDRESS = {
    "uprn": "100110000001",
    "full_address": "1 High Street, Hartlepool, TS26 0BL",
    "postcode": "TS26 0BL",
    "address_line_1": "1 High Street",
    "house_number_or_name": "1",
    "street": "High Street",
}


@pytest.fixture
def addresses(monkeypatch):
    """The address API, stubbed: returns `result` (or raises it) and records the postcodes asked for."""

    class Stub:
        result: object = [ADDRESS]
        seen: list[str] = []

    stub = Stub()
    stub.seen = []

    async def search(postcode):
        stub.seen.append(postcode)
        if isinstance(stub.result, BaseException):
            raise stub.result
        return stub.result

    monkeypatch.setattr(address_lookup, "search_addresses", search)
    return stub


@pytest.mark.asyncio(loop_scope="session")
async def test_find_wired_council(client, addresses):
    r = await client.get("/v2/find", params={"postcode": "ts26 0bl"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body == {
        "postcode": "TS26 0BL",
        "council": HARTLEPOOL,
        "council_name": LAD_LOOKUP[HARTLEPOOL]["name"],
        "candidates": [],
        "deeplink": None,
        "addresses": [ADDRESS],
    }
    assert addresses.seen == ["ts26 0bl"]


@pytest.mark.asyncio(loop_scope="session")
async def test_find_unwired_council_gives_deeplink(client, addresses):
    r = await client.get("/v2/find", params={"postcode": UNWIRED_POSTCODE})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["council"] is None and body["addresses"] == []
    assert body["council_name"] == "Fylde"
    assert body["deeplink"]["url"] == LAD_LOOKUP[UNWIRED]["url"]
    assert body["deeplink"]["reason"]
    assert addresses.seen == []  # no address step for a council we can't look up


@pytest.mark.asyncio(loop_scope="session")
async def test_find_needs_browser_council_gives_deeplink(client, addresses):
    r = await client.get("/v2/find", params={"postcode": "CV3 2LS"})
    assert r.status_code == 200, r.text
    assert r.json()["council"] is None
    assert r.json()["deeplink"]["url"] == load("coventry").meta.url
    assert addresses.seen == []


@pytest.mark.asyncio(loop_scope="session")
@pytest.mark.parametrize(
    ("error", "status"),
    [
        (httpx.HTTPStatusError("boom", request=httpx.Request("GET", "http://x"), response=httpx.Response(500)), 503),
        (httpx.ReadTimeout("slow"), 504),
        (KeyError("results"), 503),
    ],
)
async def test_find_address_api_failure(client, addresses, error, status):
    addresses.result = error
    r = await client.get("/v2/find", params={"postcode": "TS26 0BL"})
    assert r.status_code == status
    assert "address lookup" in r.json()["detail"]


@pytest.mark.asyncio(loop_scope="session")
async def test_find_unknown_postcode_is_404(client, addresses):
    r = await client.get("/v2/find", params={"postcode": "ZZ99 9ZZ"})
    assert r.status_code == 404
    assert addresses.seen == []


@pytest.mark.asyncio(loop_scope="session")
async def test_find_needs_a_postcode(client):
    assert (await client.get("/v2/find")).status_code == 422


@pytest.mark.asyncio(loop_scope="session")
async def test_find_without_turnstile_token_answers_council_only(client, addresses, monkeypatch):
    monkeypatch.setattr(config, "TURNSTILE_SECRET", "secret")
    r = await client.get("/v2/find", params={"postcode": "TS26 0BL"})
    assert r.status_code == 200
    body = r.json()
    assert body["council"] == HARTLEPOOL
    assert body["addresses"] is None
    assert addresses.seen == []


@pytest.mark.asyncio(loop_scope="session")
async def test_find_with_failed_turnstile_token_is_403(client, addresses, monkeypatch):
    monkeypatch.setattr(config, "TURNSTILE_SECRET", "secret")

    async def siteverify(self, url, **kwargs):
        return httpx.Response(200, json={"success": False}, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.AsyncClient, "post", siteverify)
    r = await client.get(
        "/v2/find", params={"postcode": "TS26 0BL"}, headers={"X-Turnstile-Token": "bad"}
    )
    assert r.status_code == 403
    assert addresses.seen == []


@pytest.mark.asyncio(loop_scope="session")
async def test_old_find_route_is_gone(client):
    r = await client.get(f"/v2/{HARTLEPOOL}/find", params={"postcode": "TS26 0BL"})
    assert r.status_code == 404


# --- schema -------------------------------------------------------------------------


@pytest.mark.asyncio(loop_scope="session")
async def test_routes_are_in_the_openapi_schema(client):
    paths = (await client.get("/v2/openapi.json")).json()["paths"]
    assert "/api/v2/find" in paths
    for route in ("view/{uprn}", "subscribe/{uprn}", "download/{uprn}"):
        assert f"/api/v2/{{lad}}/{route}" in paths
    for route in ("councils", "health", "status", "metrics"):
        assert f"/api/v2/{route}" in paths
    assert not [p for p in paths if not p.startswith("/api/v2/")]
