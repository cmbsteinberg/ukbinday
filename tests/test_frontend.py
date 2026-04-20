"""
Basic tests for app startup, frontend pages, and API route availability.

Usage:
    uv run pytest tests/test_frontend.py -v
"""

import httpx
import pytest
import pytest_asyncio
from asgi_lifespan import LifespanManager

from api.main import app

BASE_URL = "http://testserver"


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def client():
    async with LifespanManager(app) as manager:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=manager.app), base_url=BASE_URL
        ) as c:
            yield c


@pytest.mark.asyncio(loop_scope="session")
async def test_landing_page(client):
    resp = await client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert 'id="postcode-form"' in resp.text
    assert 'href="/api-docs"' in resp.text


@pytest.mark.asyncio(loop_scope="session")
async def test_api_docs_page(client):
    resp = await client.get("/api-docs")
    assert resp.status_code == 200
    assert "/api/v1/lookup/{uprn}" in resp.text
    assert 'href="/api/v1/docs"' in resp.text


@pytest.mark.asyncio(loop_scope="session")
async def test_openapi_and_docs(client):
    schema_resp = await client.get("/api/v1/openapi.json")
    assert schema_resp.status_code == 200
    assert schema_resp.json()["info"]["title"] == "UK Bin Collection API"

    assert (await client.get("/api/v1/docs")).status_code == 200
    assert (await client.get("/api/v1/redoc")).status_code == 200


@pytest.mark.asyncio(loop_scope="session")
async def test_councils_and_health(client):
    resp = await client.get("/api/v1/councils")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) > 0
    assert "id" in data[0] and "name" in data[0]

    health = await client.get("/api/v1/health")
    assert health.status_code == 200
    assert isinstance(health.json(), list)


@pytest.mark.asyncio(loop_scope="session")
async def test_v1_prefix(client):
    assert (await client.get("/api/v1/councils")).status_code == 200
    assert (await client.get("/api/councils")).status_code == 404

@pytest.mark.asyncio(loop_scope="session")
async def test_lookup_error_cases(client):
    assert (
        await client.get("/api/v1/lookup/123456?council=nonexistent")
    ).status_code == 404
    assert (await client.get("/api/v1/lookup/123456")).status_code == 422


@pytest.mark.asyncio(loop_scope="session")
async def test_calendar_error_cases(client):
    # Missing council param → 422
    resp = await client.get("/api/v1/calendar/123456")
    assert resp.status_code == 422

    # Unknown council → 404
    resp = await client.get("/api/v1/calendar/123456?council=nonexistent")
    assert resp.status_code == 404


@pytest.mark.asyncio(loop_scope="session")
async def test_cors(client):
    # Request from allowed origin gets CORS headers
    resp = await client.options(
        "/api/v1/councils",
        headers={
            "Origin": "https://bins.lovesguinness.com",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert (
        resp.headers.get("access-control-allow-origin")
        == "https://bins.lovesguinness.com"
    )

    # Request from disallowed origin does not get allow-origin header
    resp2 = await client.options(
        "/api/v1/councils",
        headers={
            "Origin": "http://evil.com",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert resp2.headers.get("access-control-allow-origin") is None
