"""
Playwright integration tests — launches the API and runs test cases for
Playwright-based scrapers only (those using async_playwright).

Separated from test_integration.py because Playwright scrapers are much
heavier: each spins up a Chromium instance (~562 MB), so running them
alongside requests-based scrapers makes it hard to diagnose failures
and manage resources.

Usage:
    uv run pytest tests/test_playwright.py -v
    uv run pytest tests/test_playwright.py -v -k "teignbridge"
    uv run pytest tests/test_playwright.py -v --tb=short
"""

import asyncio
import json
import time
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from asgi_lifespan import LifespanManager

from api.main import app

TEST_CASES_PATH = Path(__file__).parent / "test_cases.json"
OUTPUT_PATH = Path(__file__).parent / "playwright_output.json"
SCRAPERS_DIR = Path(__file__).resolve().parent.parent / "api" / "scrapers"
BASE_URL = "http://testserver/api/v1"

MAX_CONCURRENCY = 10  # Lower than integration — each request spawns Chromium
REQUEST_TIMEOUT = 120


def _playwright_scraper_ids() -> set[str]:
    """Return the set of scraper IDs that use Playwright."""
    ids = set()
    for p in SCRAPERS_DIR.glob("*.py"):
        if p.name == "__init__.py":
            continue
        try:
            source = p.read_text()
        except OSError:
            continue
        if "_get_browser_pool" in source or "async_playwright" in source:
            ids.add(p.stem)
    return ids


def _load_playwright_test_cases() -> list[tuple[str, str, dict]]:
    """Load test cases for Playwright scrapers only."""
    data = json.loads(TEST_CASES_PATH.read_text())
    pw_ids = _playwright_scraper_ids()
    cases = []
    for council, entries in sorted(data.items()):
        if council not in pw_ids:
            continue
        for entry in entries:
            cases.append((council, entry["label"], entry["params"]))
    return cases


TEST_DATA = _load_playwright_test_cases()


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def client():
    async with LifespanManager(app) as manager:
        transport = httpx.ASGITransport(app=manager.app)
        async with httpx.AsyncClient(
            transport=transport, base_url=BASE_URL, timeout=REQUEST_TIMEOUT
        ) as c:
            yield c


async def _run_lookup(
    client: httpx.AsyncClient,
    semaphore: asyncio.Semaphore,
    council: str,
    label: str,
    params: dict,
) -> dict:
    """Execute a single lookup and capture diagnostics."""
    params = dict(params)
    uprn = str(params.pop("uprn", "0"))
    query = {"council": council, **params}

    result = {
        "council": council,
        "label": label,
        "uprn": uprn,
        "query_params": query,
        "endpoint": f"/lookup/{uprn}",
        "passed": False,
    }

    async with semaphore:
        start = time.monotonic()
        try:
            resp = await client.get(f"/lookup/{uprn}", params=query)
        except httpx.TimeoutException as exc:
            elapsed = time.monotonic() - start
            result.update(
                elapsed_s=round(elapsed, 3),
                error_type="timeout",
                error_class=type(exc).__name__,
                error_message=str(exc),
            )
            return result
        except httpx.HTTPError as exc:
            elapsed = time.monotonic() - start
            result.update(
                elapsed_s=round(elapsed, 3),
                error_type="http_error",
                error_class=type(exc).__name__,
                error_message=str(exc),
            )
            return result
        except Exception as exc:
            elapsed = time.monotonic() - start
            result.update(
                elapsed_s=round(elapsed, 3),
                error_type="exception",
                error_class=type(exc).__name__,
                error_message=str(exc),
            )
            return result

    elapsed = time.monotonic() - start
    result["elapsed_s"] = round(elapsed, 3)
    result["status_code"] = resp.status_code
    result["response_headers"] = dict(resp.headers)
    result["response_size_bytes"] = len(resp.content)
    result["response_body_preview"] = resp.text[:2000]

    try:
        body = resp.json()
        result["response_json"] = body
    except (json.JSONDecodeError, ValueError):
        result["error_type"] = "invalid_json"
        return result

    if resp.status_code == 200 and "collections" in body:
        result["passed"] = True
        result["collections_count"] = len(body["collections"])
        if body["collections"]:
            result["first_collection"] = body["collections"][0]
            result["last_collection"] = body["collections"][-1]
            types_seen = sorted(set(c.get("type", "") for c in body["collections"]))
            result["collection_types"] = types_seen
    elif resp.status_code != 200:
        result["error_type"] = f"http_{resp.status_code}"
        if "detail" in body:
            result["error_detail"] = body["detail"]
    else:
        result["error_type"] = "missing_collections_key"
        result["response_keys"] = list(body.keys())

    return result


_results_cache: dict[str, dict] = {}


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def all_results(client: httpx.AsyncClient):
    if _results_cache:
        return _results_cache

    semaphore = asyncio.Semaphore(MAX_CONCURRENCY)
    batch_start = time.monotonic()

    results = await asyncio.gather(
        *[
            _run_lookup(client, semaphore, council, label, params)
            for council, label, params in TEST_DATA
        ]
    )

    batch_elapsed = time.monotonic() - batch_start

    for r in results:
        _results_cache[f"{r['council']}|{r['label']}"] = r

    passed = [r for r in results if r["passed"]]
    failed = [r for r in results if not r["passed"]]

    failure_groups: dict[str, list] = {}
    for r in failed:
        err_type = r.get("error_type", "unknown")
        failure_groups.setdefault(err_type, []).append(
            {
                "council": r["council"],
                "label": r["label"],
                "uprn": r["uprn"],
                "elapsed_s": r.get("elapsed_s"),
                "status_code": r.get("status_code"),
                "error_class": r.get("error_class"),
                "error_detail": r.get("error_detail"),
                "error_message": r.get("error_message", "")[:300],
            }
        )

    timings = [r["elapsed_s"] for r in results if "elapsed_s" in r]
    timing_stats = {}
    if timings:
        timings_sorted = sorted(timings)
        timing_stats = {
            "min_s": timings_sorted[0],
            "max_s": timings_sorted[-1],
            "median_s": timings_sorted[len(timings_sorted) // 2],
            "mean_s": round(sum(timings) / len(timings), 3),
            "p95_s": timings_sorted[int(len(timings_sorted) * 0.95)],
            "total_wall_clock_s": round(batch_elapsed, 3),
        }

    summary = {
        "total_test_cases": len(results),
        "passed": len(passed),
        "failed": len(failed),
        "pass_rate": f"{len(passed) * 100 / len(results):.1f}%" if results else "N/A",
        "concurrency": MAX_CONCURRENCY,
        "timeout_s": REQUEST_TIMEOUT,
        "timing": timing_stats,
        "failure_groups": {
            k: {"count": len(v), "cases": v}
            for k, v in sorted(failure_groups.items(), key=lambda x: -len(x[1]))
        },
        "all_results": results,
    }

    OUTPUT_PATH.write_text(json.dumps(summary, indent=2, default=str) + "\n")

    return _results_cache


@pytest.mark.asyncio(loop_scope="session")
@pytest.mark.parametrize(
    "council, label, params",
    TEST_DATA,
    ids=[f"{council}|{label}" for council, label, _ in TEST_DATA],
)
async def test_playwright_scraper(all_results, council: str, label: str, params: dict):
    key = f"{council}|{label}"
    r = all_results[key]

    if r["passed"]:
        return

    lines = [f"FAILED: {council} / {label}"]
    lines.append(f"  Endpoint:      GET {r['endpoint']}")
    lines.append(f"  UPRN:          {r['uprn']}")
    lines.append(f"  Query params:  {json.dumps(r['query_params'])}")
    lines.append(f"  Elapsed:       {r.get('elapsed_s', '?')}s")

    if "status_code" in r:
        lines.append(f"  Status code:   {r['status_code']}")
    if r.get("response_size_bytes") is not None:
        lines.append(f"  Response size: {r['response_size_bytes']} bytes")

    err_type = r.get("error_type", "unknown")
    lines.append(f"  Error type:    {err_type}")

    if "error_class" in r:
        lines.append(f"  Error class:   {r['error_class']}")
    if "error_detail" in r:
        lines.append(f"  Error detail:  {r['error_detail']}")
    if "error_message" in r:
        lines.append(f"  Error message: {r['error_message'][:500]}")

    preview = r.get("response_body_preview", "")
    if preview:
        lines.append(f"  Response body: {preview[:500]}")

    pytest.fail("\n".join(lines))
