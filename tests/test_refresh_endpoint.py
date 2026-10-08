"""
Cron-triggered refresh: GET /api/v2/internal/refresh auth, shard selection,
deadline, and the heartbeat /metrics reads. Scrapers are stubbed; no network.

Usage:
    uv run pytest tests/test_refresh_endpoint.py -v
"""

import asyncio
import datetime
import time

import httpx
import pytest
import pytest_asyncio
from asgi_lifespan import LifespanManager

from api import config
from api.councils._base import Collection
from api.councils._base.discovery import load
from api.main import app
from api.services.blob_store import LocalBlobStore
from api.services.ics_cache import IcsCache
from api.services.refresh_job import RefreshJob

pytestmark = pytest.mark.api

BRISTOL = "E06000023"  # module bristol
SECRET = "s3cret"
AUTH = {"Authorization": f"Bearer {SECRET}"}
FIRST_UPRN = 900200000000  # even, so UPRNs alternate between shards 0 and 1 of 2


@pytest_asyncio.fixture(scope="module", loop_scope="session")
async def client():
    async with LifespanManager(app) as manager:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=manager.app),
            base_url="http://testserver/api/v2",
        ) as c:
            yield c


@pytest.fixture
def cron_secret(monkeypatch):
    monkeypatch.setattr(config, "CRON_SECRET", SECRET)


@pytest_asyncio.fixture(loop_scope="session")
async def cache(tmp_path, monkeypatch):
    """An empty cache of its own, swapped in for the app's: a refresh pass
    would otherwise retry every failure sidecar other tests left behind."""
    cache = IcsCache(LocalBlobStore(tmp_path), canonical_id=app.state.registry.canonical_id)
    monkeypatch.setattr(app.state, "ics_cache", cache)
    return cache


@pytest.fixture
def fetched(monkeypatch):
    """The UPRNs the bristol module was asked for."""
    uprns: list[str] = []

    async def fetch(address, http):
        uprns.append(address.uprn)
        return [Collection(datetime.date.today() + datetime.timedelta(days=3), "Recycling")]

    monkeypatch.setattr(load("bristol"), "fetch", fetch)
    return uprns


async def seed(cache, n=4) -> list[str]:
    """n sidecars with no upcoming collections, so all are due."""
    uprns = [str(FIRST_UPRN + i) for i in range(n)]
    for u in uprns:
        await cache.write(u, BRISTOL, {"uprn": u, "postcode": "BS14 8ES"}, [])
    return uprns


# --- auth and params ---------------------------------------------------------


@pytest.mark.asyncio(loop_scope="session")
async def test_refused_when_secret_unset(client, monkeypatch):
    monkeypatch.setattr(config, "CRON_SECRET", "")
    assert (await client.get("/internal/refresh")).status_code == 403
    # An empty token must not match an unset secret
    assert (await client.get("/internal/refresh", headers={"Authorization": "Bearer "})).status_code == 403


@pytest.mark.asyncio(loop_scope="session")
@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer nope"}, {"Authorization": SECRET}])
async def test_unauthorized(client, cron_secret, headers):
    assert (await client.get("/internal/refresh", headers=headers)).status_code == 401


@pytest.mark.asyncio(loop_scope="session")
@pytest.mark.parametrize("params", [{"shard": 2, "of": 2}, {"shard": -1, "of": 2}, {"of": 0}, {"shard": "x"}])
async def test_bad_shard_params(client, cron_secret, params):
    assert (await client.get("/internal/refresh", params=params, headers=AUTH)).status_code == 422


@pytest.mark.asyncio(loop_scope="session")
async def test_params_checked_after_auth(client, cron_secret):
    assert (await client.get("/internal/refresh", params={"of": 0})).status_code == 401


@pytest.mark.asyncio(loop_scope="session")
async def test_not_in_openapi(client):
    r = await client.get("http://testserver/api/v2/openapi.json")
    assert all("internal" not in path for path in r.json()["paths"])


# --- a pass ------------------------------------------------------------------


@pytest.mark.asyncio(loop_scope="session")
async def test_refresh_runs_only_its_shard(client, cron_secret, cache, fetched):
    uprns = await seed(cache)
    r = await client.get("/internal/refresh", params={"shard": 1, "of": 2}, headers=AUTH)
    assert r.status_code == 200, r.text
    stats = r.json()
    assert (stats["shard"], stats["of"], stats["refreshed"], stats["failed"], stats["deferred"]) == (1, 2, 2, 0, 0)
    assert sorted(fetched) == [u for u in uprns if int(u) % 2 == 1]


@pytest.mark.asyncio(loop_scope="session")
async def test_heartbeat_per_shard_and_metrics(client, cron_secret, cache, fetched):
    await seed(cache)
    for shard in (0, 1):
        r = await client.get("/internal/refresh", params={"shard": shard, "of": 2}, headers=AUTH)
        assert r.status_code == 200, r.text

    heartbeat = await cache.read_heartbeat()
    assert heartbeat["of"] == 2
    assert {s: h["entries"] for s, h in heartbeat["shards"].items()} == {"0": 2, "1": 2}
    assert heartbeat["shards"]["1"]["stats"]["shard"] == 1

    info = (await client.get("/metrics")).json()["ics_cache"]
    assert info["entries"] == 4
    assert info["shards_expected"] == 2
    assert 0 <= info["last_refresh_age_seconds"] < 60
    assert set(info["last_refresh_stats"]) == {"0", "1"}


@pytest.mark.asyncio(loop_scope="session")
async def test_heartbeat_forgets_a_retired_shard_count(cache):
    await cache.write_heartbeat(0, 4, 10, {})
    await cache.write_heartbeat(3, 4, 10, {})
    await cache.write_heartbeat(0, 1, 40, {})
    assert (await cache.read_heartbeat())["shards"].keys() == {"0"}


@pytest.mark.asyncio(loop_scope="session")
async def test_metrics_without_a_heartbeat(client, cache):
    info = (await client.get("/metrics")).json()["ics_cache"]
    assert info["entries"] is None and info["last_refresh_age_seconds"] is None


@pytest.mark.asyncio(loop_scope="session")
async def test_passed_deadline_queues_nothing(cache, fetched):
    await seed(cache)
    stats = await RefreshJob(cache, app.state.registry).run_once(deadline=time.monotonic() - 1)
    assert (stats.refreshed, stats.deferred) == (0, 4)
    assert fetched == []
    # Deferred sidecars stay as they were, so the next pass takes them
    assert (await RefreshJob(cache, app.state.registry).run_once()).refreshed == 4


@pytest.mark.asyncio(loop_scope="session")
async def test_deadline_stops_queued_work(cache, monkeypatch):
    """Work queued before the deadline but not started by it is deferred, not run."""
    await seed(cache)
    started: list[str] = []

    async def fetch(address, http):
        started.append(address.uprn)
        await asyncio.sleep(0.4)  # outlasts the deadline
        return [Collection(datetime.date.today() + datetime.timedelta(days=3), "Recycling")]

    monkeypatch.setattr(load("bristol"), "fetch", fetch)
    job = RefreshJob(cache, app.state.registry, concurrency=1)
    stats = await job.run_once(deadline=time.monotonic() + 0.2)
    assert (stats.refreshed, stats.deferred) == (1, 3)
    assert len(started) == 1


@pytest.mark.asyncio(loop_scope="session")
async def test_four_concurrent_shards_keep_every_heartbeat(client, cron_secret, cache, fetched):
    uprns = await seed(cache, n=8)
    responses = await asyncio.gather(*(
        client.get("/internal/refresh", params={"shard": shard, "of": 4}, headers=AUTH)
        for shard in range(4)
    ))
    assert all(response.status_code == 200 for response in responses)
    assert sorted(fetched) == uprns
    info = (await client.get("/metrics")).json()["ics_cache"]
    assert info["entries"] == 8
    assert info["shards_expected"] == 4
    assert set(info["last_refresh_stats"]) == {"0", "1", "2", "3"}
    assert all(stats["refreshed"] == 2 for stats in info["last_refresh_stats"].values())


@pytest.mark.asyncio(loop_scope="session")
async def test_legacy_heartbeat_read_until_first_new_shard(cache):
    import json

    from api.services.ics_cache import HEARTBEAT_KEY

    legacy = {"of": 1, "shards": {"0": {"last_run": "2026-10-01T05:00:00+00:00", "entries": 8, "stats": {}}}}
    cache.store.put(HEARTBEAT_KEY, json.dumps(legacy).encode())
    assert await cache.read_heartbeat() == legacy
    await cache.write_heartbeat(0, 4, 2, {})
    heartbeat = await cache.read_heartbeat()
    assert heartbeat["of"] == 4
    assert set(heartbeat["shards"]) == {"0"}
