"""Running one LAD test case against /{lad}/view/{uprn}, shared by every runner.

tests/test_lad_integration.py (in-process, against the app) and
scripts/vercel_probe.py (over HTTP, against a deployment) both send a case the
same way and classify the response the same way, so a case outcome means the
same thing in both. Outcomes from `view`:

  pass            200 with at least one date
  empty           200 with no dates (wrong property or a parse break)
  input_rejected  422: the scraper refused the params
  deeplink        200 with a deeplink instead of dates: the scraper
                  raised NeedsBrowser (captcha, login)
  network         the council's site couldn't be reached (503, or a 200
                  fallback deeplink with `X-Scrape-Failure: network`)
  timeout         the scrape timed out (504, `X-Scrape-Failure: timeout`, or a
                  client-side timeout)
  lock_contention 503: another request holds the UPRN's scrape lock
  scraper_error   anything else

`network`, `timeout` and `lock_contention` are provisional: each runner turns
them into `unreachable` or `upstream_error` for itself (the live test probes
the host from the test machine; the Vercel probe has no such probe and calls
them `upstream_error`). Both are then fed to scripts/lad_status.py.
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from urllib.parse import quote

import httpx

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CASES_PATH = ROOT / "tests" / "lad_test_cases.json"

NETWORKISH = {"network", "timeout"}
# Outcomes that are final on the first attempt. 200-empty is cached as a
# success by the app, so retrying it would only read it back; 422 is
# deterministic; a deeplink is the scraper's own answer.
FINAL_OUTCOMES = {"pass", "empty", "input_rejected", "deeplink"}


def load_lads(
    path: Path = DEFAULT_CASES_PATH,
    codes: set[str] | None = None,
    sources: set[str] | None = None,
) -> dict[str, dict]:
    """LAD code -> cases-file entry, optionally limited to LAD codes and case sources."""
    if not path.exists():
        return {}
    lads = {}
    for code, entry in sorted(json.loads(path.read_text()).items()):
        if code.startswith("_") or (codes and code not in codes):
            continue
        cases = [c for c in entry["cases"] if not sources or c["source"] in sources]
        lads[code] = {**entry, "cases": cases}
    return lads


def job_key(module: str, params: dict) -> str:
    """Two LADs sharing a module and a fixture must not race on one UPRN, so
    jobs dedupe on the module; the request carries the first LAD's code."""
    return module + "|" + json.dumps(params, sort_keys=True)


def view_request(council: str, params: dict) -> tuple[str, dict]:
    """(path, query) for a case. `council` is the LAD code, as /find hands it
    to the frontend; the query is what the frontend sends besides the UPRN."""
    params = dict(params)
    uprn = str(params.pop("uprn", "") or "0").strip()
    return f"/{quote(council, safe='')}/view/{quote(uprn, safe='')}", {k: v for k, v in params.items() if v}


def classify_http(status: int, body: dict | None) -> str:
    detail = (body or {}).get("detail", "") if isinstance(body, dict) else ""
    if status == 422:
        return "input_rejected"
    if status == 504:
        return "timeout"
    if status == 503 and "couldn't reach" in detail:
        return "network"
    if status == 503 and "already fetching" in detail:
        return "lock_contention"
    return "scraper_error"


def classify_response(resp: httpx.Response) -> dict:
    """A /view response as a case result: `outcome` plus status_code and detail."""
    out: dict = {"status_code": resp.status_code}
    try:
        body = resp.json()
    except ValueError:
        return {**out, "outcome": "scraper_error", "error": "invalid json"}
    failure = resp.headers.get("X-Scrape-Failure")
    if resp.status_code == 200 and failure:
        out["outcome"] = {"network": "network", "timeout": "timeout"}.get(failure, "scraper_error")
        out["error"] = str((body.get("deeplink") or {}).get("reason", ""))[:300]
        return out
    if resp.status_code == 200:
        cols = body.get("dates") or []
        out["collections_count"] = len(cols)
        if cols:
            out["first"] = cols[0]
            out["types"] = sorted({(c.get("type") or {}).get("label", "") for c in cols})
        # DATA_DIR is a fresh tempdir per session and the cache only hits on
        # the same scraper + real UPRN, so a hit means another case in this
        # run already scraped this exact property. Keep the flag visible.
        out["cached"] = bool(body.get("cached"))
        out["outcome"] = "pass" if cols else "deeplink" if body.get("deeplink") else "empty"
        if out["outcome"] == "deeplink":
            out["error"] = str(body["deeplink"].get("reason", ""))[:300]
        return out
    out["outcome"] = classify_http(resp.status_code, body)
    out["error"] = str(body.get("detail", ""))[:300] if isinstance(body, dict) else ""
    return out


async def view(client: httpx.AsyncClient, council: str, params: dict) -> dict:
    """Run one case through `GET /{lad}/view/{uprn}` on a client whose base_url ends in /api/v2."""
    path, query = view_request(council, params)
    start = time.monotonic()

    def elapsed() -> float:
        return round(time.monotonic() - start, 2)

    try:
        resp = await client.get(path, params=query)
    except (httpx.TimeoutException, asyncio.TimeoutError) as exc:
        return {"outcome": "timeout", "error": type(exc).__name__, "elapsed_s": elapsed()}
    except Exception as exc:  # noqa: BLE001 - transport-level (the test sets raise_app_exceptions=False)
        return {"outcome": "scraper_error", "error": f"{type(exc).__name__}: {exc}"[:300], "elapsed_s": elapsed()}
    return {**classify_response(resp), "elapsed_s": elapsed()}
