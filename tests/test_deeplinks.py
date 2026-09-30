"""Deeplink serving for unwired councils — service, routes, and target data.

A deeplink is the "check on the council website instead" response for a LAD
with no scraper (see api/services/deeplinks.py). These tests pin the contract
the frontend card relies on, and guard the composed targets: a dead target is
worse than none, since the user lands on a 404.

Usage:
    uv run pytest tests/test_deeplinks.py -v
"""

import json
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from asgi_lifespan import LifespanManager

from api.main import app
from api.services import deeplinks
from pipeline.shared import load_deeplink_urls, load_unwired_lads

pytestmark = pytest.mark.api

BASE_URL = "http://testserver"

LAD_LOOKUP = json.loads(
    (Path(__file__).parent.parent / "api" / "data" / "lad_lookup.json").read_text()
)


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def client():
    async with LifespanManager(app) as manager:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=manager.app), base_url=BASE_URL
        ) as c:
            yield c


def _unwired_code() -> str:
    """A LAD that is unwired and has a deeplink target — Fylde by default."""
    return "E07000119"


# --- service ---------------------------------------------------------------


def test_resolve_unwired_lad():
    target = deeplinks.resolve(_unwired_code())
    assert target is not None
    assert target.lad_code == _unwired_code()
    assert target.council_name == "Fylde"
    assert target.url.startswith("https://")
    assert target.reason  # never empty — the card renders it


def test_resolve_prefers_council_url_over_govuk():
    entry = LAD_LOOKUP[_unwired_code()]
    assert entry["url"] and entry["url"] != entry["govuk_url"]
    assert deeplinks.resolve(_unwired_code()).url == entry["url"]


def test_resolve_falls_back_to_govuk_url():
    code = "E06000053"  # Isles of Scilly — no override, GOV.UK page is live
    assert LAD_LOOKUP[code]["url"] is None
    assert deeplinks.resolve(code).url == LAD_LOOKUP[code]["govuk_url"]


def test_resolve_returns_none_for_wired_lad():
    wired = next(c for c, e in LAD_LOOKUP.items() if e["scraper_id"])
    assert deeplinks.resolve(wired) is None


def test_resolve_returns_none_for_unknown_lad():
    assert deeplinks.resolve("E99999999") is None


def test_resolve_by_council_param_accepts_code_and_name():
    by_code = deeplinks.resolve_by_council_param(_unwired_code())
    assert by_code is not None
    assert deeplinks.resolve_by_council_param("fylde") == by_code


def test_resolve_by_council_param_ignores_wired_scraper_ids():
    scraper_id = next(e["scraper_id"] for e in LAD_LOOKUP.values() if e["scraper_id"])
    assert deeplinks.resolve_by_council_param(scraper_id) is None
    assert deeplinks.resolve_by_council_param("nonexistent") is None


# --- routes ----------------------------------------------------------------


@pytest.mark.asyncio(loop_scope="session")
async def test_lookup_returns_deeplink_not_404(client):
    resp = await client.get(f"/api/v1/lookup/123456?council={_unwired_code()}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["collections"] == []
    assert body["deeplink"]["url"] == LAD_LOOKUP[_unwired_code()]["url"]
    assert body["deeplink"]["council_name"] == "Fylde"
    assert body["deeplink"]["reason"]


@pytest.mark.asyncio(loop_scope="session")
async def test_calendar_redirects_to_deeplink(client):
    resp = await client.get(f"/api/v1/calendar/123456?council={_unwired_code()}")
    assert resp.status_code == 302
    assert resp.headers["location"] == LAD_LOOKUP[_unwired_code()]["url"]


@pytest.mark.asyncio(loop_scope="session")
async def test_wired_council_gets_no_deeplink(client):
    """A wired council still 404s on an unknown *scraper*, never deeplinks."""
    resp = await client.get("/api/v1/lookup/123456?council=nonexistent")
    assert resp.status_code == 404
    assert "deeplink" not in resp.text


# --- composed targets ------------------------------------------------------


def test_every_unwired_lad_has_a_deeplink_target():
    """No unwired LAD may serve a bare 404 — url or govuk_url must exist."""
    missing = [
        code
        for code, entry in LAD_LOOKUP.items()
        if not entry["scraper_id"] and not (entry["url"] or entry["govuk_url"])
    ]
    assert missing == []


def test_deeplink_url_overrides_reach_the_lookup():
    """An override that doesn't show up composed is silently doing nothing."""
    for code, url in load_deeplink_urls().items():
        assert code in LAD_LOOKUP, f"{code} is not a LAD in lad_lookup.json"
        assert LAD_LOOKUP[code]["scraper_id"] is None, f"{code} is wired"
        assert LAD_LOOKUP[code]["url"] == url, f"{code} did not take the override"


def test_unwired_lads_ship_their_reason_as_status():
    for code, reason in load_unwired_lads().items():
        if code not in LAD_LOOKUP:
            continue  # code ONSPD no longer returns — dropped at compose time
        assert LAD_LOOKUP[code]["scraper_id"] is None, f"{code} was re-wired"
        assert LAD_LOOKUP[code]["status"] == reason
        assert deeplinks.resolve(code).reason == reason
