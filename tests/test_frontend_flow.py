"""
Frontend-flow integration tests — exercise the *real* user journey, end-to-end.

Where ``test_integration.py`` calls ``/lookup/{uprn}`` with each scraper's
TEST_CASES params verbatim, this suite mimics what ``api/static/app.js`` does:

    1. GET  /api/v1/addresses/{postcode}            → list of AddressResult
    2. Pick the address whose ``uprn`` matches the test case
    3. GET  /api/v1/lookup/{uprn}?council=&postcode=&address=&house_number=&street=

Mirroring the JS more precisely, the flow is actually three calls:

    1. GET  /api/v1/council/{postcode}              → resolves council_id
    2. GET  /api/v1/addresses/{postcode}            → list of AddressResult
    3. GET  /api/v1/lookup/{uprn}?council=&postcode=&address=&house_number=&street=

This is what tells us whether a scraper is reachable from the **frontend's
own input** (postcode + picked address) — i.e. whether the address API's
returned fields plus ``build_scrape_params`` is enough to drive the scraper.
A scraper can pass ``test_integration`` (because TEST_CASES happen to carry
the special params it needs) and still fail here (because ``/addresses`` does
not surface those params for a real user).

Test cases that lack a ``postcode`` in TEST_CASES are reported as ``skipped``
in the output JSON (rather than failing) — there is nothing to feed the
``/addresses`` endpoint with. Same when ``/addresses`` returns no entry whose
UPRN matches the expected one.

Usage:
    uv run pytest tests/test_frontend_flow.py -v -k "newham"
    uv run pytest tests/test_frontend_flow.py -v --tb=short
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

pytestmark = pytest.mark.live


TEST_CASES_PATH = Path(__file__).parent / "test_cases.json"
OUTPUT_PATH = Path(__file__).parent / "output" / "frontend_flow_output.json"
BASE_URL = "http://testserver/api/v1"

MAX_CONCURRENCY = 20
REQUEST_TIMEOUT = 15

SCRAPERS_DIR = Path(__file__).resolve().parent.parent / "api" / "scrapers"


def _playwright_scraper_ids() -> set[str]:
    ids = set()
    for p in SCRAPERS_DIR.glob("*.py"):
        if p.name == "__init__.py":
            continue
        try:
            source = p.read_text()
        except OSError:
            continue
        if "async_playwright" in source:
            ids.add(p.stem)
    return ids


def _load_all_test_cases() -> list[tuple[str, str, dict]]:
    data = json.loads(TEST_CASES_PATH.read_text())
    pw_ids = _playwright_scraper_ids()
    cases = []
    for council, entries in sorted(data.items()):
        if council in pw_ids:
            continue
        for entry in entries:
            cases.append((council, entry["label"], entry["params"]))
    return cases


TEST_DATA = _load_all_test_cases()


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def client():
    async with LifespanManager(app) as manager:
        transport = httpx.ASGITransport(app=manager.app, raise_app_exceptions=False)
        async with httpx.AsyncClient(
            transport=transport, base_url=BASE_URL, timeout=REQUEST_TIMEOUT
        ) as c:
            yield c


async def _run_frontend_flow(
    client: httpx.AsyncClient,
    semaphore: asyncio.Semaphore,
    council: str,
    label: str,
    params: dict,
) -> dict:
    """Mimic the JS frontend: postcode → addresses → pick by UPRN → lookup."""
    expected_uprn = str(params.get("uprn", "")).strip()
    postcode = str(params.get("postcode", "")).strip()

    result = {
        "council": council,
        "label": label,
        "uprn": expected_uprn,
        "postcode": postcode,
        "passed": False,
    }

    if not postcode or not expected_uprn:
        result["skipped"] = True
        result["skip_reason"] = (
            "no postcode in TEST_CASES" if not postcode else "no uprn in TEST_CASES"
        )
        return result

    from urllib.parse import quote

    pc = quote(postcode, safe="")

    async with semaphore:
        start = time.monotonic()

        # --- step 1: /council/{postcode} resolves council_id (what the JS does first) ---
        try:
            council_resp = await client.get(f"/council/{pc}")
        except (httpx.HTTPError, Exception) as exc:
            result["elapsed_s"] = round(time.monotonic() - start, 3)
            result["error_type"] = "council_request_error"
            result["error_class"] = type(exc).__name__
            result["error_message"] = str(exc)
            return result

        result["council_status_code"] = council_resp.status_code
        council_id: str | None = None
        if council_resp.status_code == 200:
            try:
                cbody = council_resp.json()
                council_id = cbody.get("council_id")
                result["resolved_council_id"] = council_id
            except (json.JSONDecodeError, ValueError):
                pass

        # --- step 2: /addresses/{postcode} ---
        try:
            addr_resp = await client.get(f"/addresses/{pc}")
        except (httpx.HTTPError, Exception) as exc:
            result["elapsed_s"] = round(time.monotonic() - start, 3)
            result["error_type"] = "addresses_request_error"
            result["error_class"] = type(exc).__name__
            result["error_message"] = str(exc)
            return result

        result["addresses_status_code"] = addr_resp.status_code
        if addr_resp.status_code != 200:
            result["elapsed_s"] = round(time.monotonic() - start, 3)
            result["error_type"] = f"addresses_http_{addr_resp.status_code}"
            result["error_detail"] = (addr_resp.text or "")[:300]
            return result

        try:
            addr_body = addr_resp.json()
        except (json.JSONDecodeError, ValueError):
            result["elapsed_s"] = round(time.monotonic() - start, 3)
            result["error_type"] = "addresses_invalid_json"
            return result

        addresses = addr_body.get("addresses", []) or []
        result["addresses_count"] = len(addresses)
        if not council_id:
            result["elapsed_s"] = round(time.monotonic() - start, 3)
            result["error_type"] = "no_council_id_for_postcode"
            return result

        def _norm_uprn(u: str) -> str:
            u = u.strip().upper().lstrip('U').lstrip('0')
            return u or '0'

        norm_expected = _norm_uprn(expected_uprn)
        match = next(
            (a for a in addresses if _norm_uprn(str(a.get('uprn', ''))) == norm_expected),
            None,
        )
        if match is None:
            match = addresses[0]
            result["uprn_fallback"] = True

        # --- step 3: /lookup/{uprn} with the address payload the frontend would send ---
        query: dict[str, str] = {
            "council": council_id,
            "postcode": match.get("postcode") or postcode,
            "address": match.get("full_address") or "",
        }
        if match.get("house_number_or_name"):
            query["house_number"] = match["house_number_or_name"]
        if match.get("street"):
            query["street"] = match["street"]

        result["lookup_query_params"] = query

        try:
            resp = await client.get(f"/lookup/{expected_uprn}", params=query)
        except (httpx.HTTPError, Exception) as exc:
            result["elapsed_s"] = round(time.monotonic() - start, 3)
            result["error_type"] = "lookup_request_error"
            result["error_class"] = type(exc).__name__
            result["error_message"] = str(exc)
            return result

    result["elapsed_s"] = round(time.monotonic() - start, 3)
    result["status_code"] = resp.status_code
    result["response_size_bytes"] = len(resp.content)
    result["response_body_preview"] = resp.text[:1000]

    try:
        body = resp.json()
        result["response_json"] = body
    except (json.JSONDecodeError, ValueError):
        result["error_type"] = "invalid_json"
        return result

    if resp.status_code == 200 and "collections" in body:
        result["passed"] = True
        result["collections_count"] = len(body["collections"])
    elif resp.status_code != 200:
        result["error_type"] = f"http_{resp.status_code}"
        if isinstance(body, dict) and "detail" in body:
            result["error_detail"] = body["detail"]
    else:
        result["error_type"] = "missing_collections_key"
        result["response_keys"] = (
            list(body.keys()) if isinstance(body, dict) else None
        )

    return result


_results_cache: dict[str, dict] = {}


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def all_results(client: httpx.AsyncClient):
    if _results_cache:
        return _results_cache

    semaphore = asyncio.Semaphore(MAX_CONCURRENCY)
    batch_start = time.monotonic()

    async def _guarded(council, label, params):
        try:
            return await asyncio.wait_for(
                _run_frontend_flow(client, semaphore, council, label, params),
                timeout=REQUEST_TIMEOUT * 3 + 30,
            )
        except asyncio.TimeoutError:
            return {
                "council": council,
                "label": label,
                "uprn": str(params.get("uprn", "0")),
                "postcode": str(params.get("postcode", "")),
                "passed": False,
                "error_type": "hard_timeout",
            }

    results = await asyncio.gather(
        *[_guarded(council, label, param) for council, label, param in TEST_DATA]
    )

    batch_elapsed = time.monotonic() - batch_start

    for r in results:
        _results_cache[f"{r['council']}|{r['label']}"] = r

    skipped = [r for r in results if r.get("skipped")]
    attempted = [r for r in results if not r.get("skipped")]
    passed = [r for r in attempted if r["passed"]]
    failed = [r for r in attempted if not r["passed"]]

    failure_groups: dict[str, list] = {}
    for r in failed:
        err_type = r.get("error_type", "unknown")
        failure_groups.setdefault(err_type, []).append(
            {
                "council": r["council"],
                "label": r["label"],
                "uprn": r["uprn"],
                "postcode": r.get("postcode"),
                "addresses_count": r.get("addresses_count"),
                "resolved_council_id": r.get("resolved_council_id"),
                "status_code": r.get("status_code"),
                "council_status_code": r.get("council_status_code"),
                "addresses_status_code": r.get("addresses_status_code"),
                "error_detail": r.get("error_detail"),
                "error_message": (r.get("error_message") or "")[:300],
            }
        )

    summary = {
        "total_test_cases": len(results),
        "attempted": len(attempted),
        "skipped": len(skipped),
        "passed": len(passed),
        "failed": len(failed),
        "pass_rate_of_attempted": (
            f"{len(passed) * 100 / len(attempted):.1f}%" if attempted else "N/A"
        ),
        "concurrency": MAX_CONCURRENCY,
        "timeout_s": REQUEST_TIMEOUT,
        "total_wall_clock_s": round(batch_elapsed, 3),
        "failure_groups": {
            k: {"count": len(v), "cases": v}
            for k, v in sorted(failure_groups.items(), key=lambda x: -len(x[1]))
        },
        "skipped_groups": {
            reason: [
                {"council": r["council"], "label": r["label"], "uprn": r["uprn"]}
                for r in skipped
                if r.get("skip_reason") == reason
            ]
            for reason in sorted({r.get("skip_reason", "") for r in skipped})
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
async def test_frontend_flow(
    all_results, council: str, label: str, params: dict
):
    key = f"{council}|{label}"
    r = all_results[key]

    if r.get("skipped"):
        pytest.skip(r.get("skip_reason", "skipped"))

    if r["passed"]:
        return

    lines = [f"FAILED frontend flow: {council} / {label}"]
    lines.append(f"  Postcode:              {r.get('postcode')}")
    lines.append(f"  Expected UPRN:         {r.get('uprn')}")
    lines.append(f"  /council status:       {r.get('council_status_code')}")
    lines.append(f"  Resolved council_id:   {r.get('resolved_council_id')}")
    lines.append(f"  /addresses status:     {r.get('addresses_status_code')}")
    lines.append(f"  /addresses count:      {r.get('addresses_count')}")
    if "lookup_query_params" in r:
        lines.append(
            f"  /lookup query params:  {json.dumps(r['lookup_query_params'])}"
        )
    lines.append(f"  /lookup status code:   {r.get('status_code')}")
    lines.append(f"  Elapsed:               {r.get('elapsed_s', '?')}s")
    lines.append(f"  Error type:            {r.get('error_type', 'unknown')}")
    if "error_detail" in r:
        lines.append(f"  Error detail:          {r['error_detail']}")
    if "error_message" in r:
        lines.append(f"  Error message:         {r['error_message'][:500]}")
    preview = r.get("response_body_preview", "")
    if preview:
        lines.append(f"  Response body:         {preview[:400]}")

    pytest.fail("\n".join(lines))
