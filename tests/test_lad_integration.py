"""
Council-level live tests: one test per wired LAD, driven by tests/lad_test_cases.json
(built by pipeline/shared/generate_lad_test_cases.py).

Each case goes through the real /{lad}/view/{uprn} route in-process, with the
same query params the frontend sends. Outcomes:

  pass            200 with at least one date
  empty           200 with no dates (wrong property or a parse break)
  input_rejected  422: the scraper refused the params
  deeplink        200 with a deeplink instead of dates: the scraper
                  raised NeedsBrowser (captcha, login), so the user is sent
                  to the council's own page

A 200 deeplink sent because the council's site failed (the X-Scrape-Failure
header) is classified by that failure, as the 503/504 it replaces was.
  unreachable     network error/timeout AND the scraper's host failed a
                  plain connectivity probe from this machine
  upstream_error  network error/blocked/timeout/HTTP error but the host answers
  scraper_error   the scraper raised something else

The LAD's status (working / broken / unverified) comes from
scripts/lad_status.py: a sampled case must pass, except for `fixture_only`
LADs, where a fixture pass counts. Unverified LADs, and LADs whose scraper
needs a browser (status `deeplink`), are skipped, not failed.

This test only writes the output file. Regenerating lad_lookup.json flags,
the README sankey, badge and coverage map is a separate explicit step:
    ./pipeline/ci/post_integration.sh

Failed cases are retried once at low concurrency before classification, so a
burst of 40 concurrent requests tripping a council's rate limit isn't
recorded as breakage.

Env knobs:
    LAD_CASES_PATH   input file (default tests/lad_test_cases.json)
    LAD_CODES        comma-separated LAD codes to run
    LAD_SOURCES      comma-separated sources to run (sampled,fixture,blind)
    LAD_OUTPUT_PATH  output file (default tests/output/lad_integration_output.json)

Usage:
    uv run pytest tests/test_lad_integration.py -v
    LAD_CODES=E08000035,S12000036 uv run pytest tests/test_lad_integration.py -v
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

import httpx
import pytest
import pytest_asyncio
from asgi_lifespan import LifespanManager

from api.main import app
from scripts.lad_cases import FINAL_OUTCOMES, NETWORKISH, job_key, load_lads, view
from scripts.lad_status import lad_status

pytestmark = pytest.mark.live

ROOT = Path(__file__).resolve().parent.parent
CASES_PATH = Path(os.environ.get("LAD_CASES_PATH", ROOT / "tests" / "lad_test_cases.json"))
OUTPUT_PATH = Path(
    os.environ.get("LAD_OUTPUT_PATH", ROOT / "tests" / "output" / "lad_integration_output.json")
)
BASE_URL = "http://testserver/api/v2"
CANARY_URL = "https://www.gov.uk/"

MAX_CONCURRENCY = 40
RETRY_CONCURRENCY = 4
REQUEST_TIMEOUT = 60  # the app enforces its own SCRAPER_TIMEOUT inside this
PROBE_TIMEOUT = 8


LADS = load_lads(
    CASES_PATH,
    codes={c for c in os.environ.get("LAD_CODES", "").split(",") if c},
    sources={s for s in os.environ.get("LAD_SOURCES", "").split(",") if s},
)


async def _probe_hosts(urls: dict[str, str]) -> dict[str, str | None]:
    """council ID -> None if its host answers any HTTP at all, else the error."""
    hosts = {sid: urlparse(u).scheme + "://" + urlparse(u).netloc for sid, u in urls.items() if u}
    results: dict[str, str | None] = {}
    sem = asyncio.Semaphore(20)

    async def probe(origin: str) -> str | None:
        async with sem:
            try:
                async with httpx.AsyncClient(timeout=PROBE_TIMEOUT, verify=False) as c:
                    await c.head(origin, follow_redirects=False)
                return None
            except Exception as exc:  # noqa: BLE001
                return type(exc).__name__

    origins = sorted(set(hosts.values()))
    probed = dict(zip(origins, await asyncio.gather(*(probe(o) for o in origins))))
    for sid in urls:
        results[sid] = probed.get(hosts.get(sid, ""), "no URL")
    return results


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def lad_results() -> dict:
    if not LADS:
        pytest.skip(f"no LAD cases in {CASES_PATH}")
    started = datetime.now(UTC)

    try:
        async with httpx.AsyncClient(timeout=PROBE_TIMEOUT) as c:
            await c.head(CANARY_URL)
        canary_ok = True
    except Exception:  # noqa: BLE001
        canary_ok = False

    async with LifespanManager(app) as manager:
        registry = app.state.registry
        # The module the registry serves each LAD with, which may differ from the
        # cases file's scraper_id when the file predates a rewiring
        module = {code: (m.module if (m := registry.get(code)) else entry["scraper_id"]) for code, entry in LADS.items()}
        transport = httpx.ASGITransport(app=manager.app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url=BASE_URL, timeout=REQUEST_TIMEOUT) as client:
            jobs: dict[str, tuple[str, dict]] = {}
            for code, entry in LADS.items():
                for case in entry["cases"]:
                    jobs.setdefault(job_key(module[code], case["params"]), (code, case["params"]))

            sem = asyncio.Semaphore(MAX_CONCURRENCY)

            async def run(key: str, sem: asyncio.Semaphore) -> tuple[str, dict]:
                council, params = jobs[key]
                async with sem:
                    return key, await view(client, council, params)

            batch_start = time.monotonic()
            results = dict(await asyncio.gather(*(run(k, sem) for k in jobs)))
            # 200-empty is cached as a success by the app, so retrying it would
            # only read it back; 422 is deterministic.
            retry = [k for k, r in results.items() if r["outcome"] not in FINAL_OUTCOMES]
            if retry:
                rsem = asyncio.Semaphore(RETRY_CONCURRENCY)
                for key, r in await asyncio.gather(*(run(k, rsem) for k in retry)):
                    r["attempts"] = 2
                    r["first_attempt"] = results[key]["outcome"]
                    results[key] = r
            batch_elapsed = round(time.monotonic() - batch_start, 1)

            needs_probe = {
                jobs[k][0] for k, r in results.items() if r["outcome"] in NETWORKISH | {"scraper_error"}
            }
            meta_urls = {c: (registry.get(c).url if registry.get(c) else "") for c in needs_probe}
            probes = await _probe_hosts(meta_urls) if meta_urls else {}

    for key, r in results.items():
        council = jobs[key][0]
        if r["outcome"] in NETWORKISH:
            probe_err = probes.get(council)
            if probe_err or not canary_ok:
                r["probe_error"] = probe_err or "canary failed"
                r["outcome"] = "unreachable"
            else:
                r["outcome"] = "upstream_error"
        elif r["outcome"] == "lock_contention":
            r["outcome"] = "upstream_error"

    lads_out: dict[str, dict] = {}
    for code, entry in LADS.items():
        cases = []
        for case in entry["cases"]:
            r = results[job_key(module[code], case["params"])]
            cases.append({"id": case["id"], "source": case["source"], "label": case.get("label"),
                          "uprn": case["params"].get("uprn"), **r})
        fixture_only = bool(entry.get("fixture_only"))
        status, reason = lad_status(cases, fixture_only)
        lads_out[code] = {"name": entry.get("name"), "scraper_id": module[code],
                          "fixture_only": fixture_only, "status": status, "reason": reason,
                          "passed_sources": sorted({c["source"] for c in cases if c["outcome"] == "pass"}),
                          "cases": cases}

    by_source: dict[str, Counter] = {}
    for e in lads_out.values():
        for c in e["cases"]:
            by_source.setdefault(c["source"], Counter())[c["outcome"]] += 1
    partial = bool(os.environ.get("LAD_CODES") or os.environ.get("LAD_SOURCES"))
    all_lads = dict(lads_out)
    if partial and OUTPUT_PATH.exists():
        # A subset run updates its LADs in place; the file stays the full
        # picture that annotate_lad_working and the sticky generator read.
        all_lads = {**json.loads(OUTPUT_PATH.read_text()).get("lads", {}), **lads_out}
    summary = {
        "lads": len(all_lads),
        "status": dict(Counter(e["status"] for e in all_lads.values())),
        "outcomes_by_source": {s: dict(c) for s, c in by_source.items()},
        "passed_sources": dict(Counter("+".join(e["passed_sources"]) or "-" for e in lads_out.values())),
    }
    out = {
        "meta": {
            "started_at": started.isoformat(timespec="seconds"),
            "wall_clock_s": batch_elapsed,
            "cases_file": str(CASES_PATH.relative_to(ROOT)) if CASES_PATH.is_relative_to(ROOT) else str(CASES_PATH),
            "jobs": len(jobs),
            "canary_ok": canary_ok,
            "partial": partial,
            "lads_run": sorted(lads_out) if partial else "all",
        },
        "summary": summary,
        "lads": dict(sorted(all_lads.items())),
    }
    OUTPUT_PATH.parent.mkdir(exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(out, indent=2, default=str) + "\n")
    return lads_out


@pytest.mark.asyncio(loop_scope="session")
@pytest.mark.parametrize("lad_code", list(LADS), ids=[f"{c}|{e['scraper_id']}" for c, e in LADS.items()])
async def test_council(lad_results, lad_code: str):
    r = lad_results[lad_code]
    if r["status"] == "working":
        return
    lines = [f"{lad_code} {r['name']} via {r['scraper_id']}: {r['status']} ({r['reason']})"]
    for c in r["cases"]:
        lines.append(
            f"  [{c['source']}] {c['outcome']:<15} uprn={c.get('uprn')} "
            f"status={c.get('status_code')} {c.get('error') or ''} {c.get('probe_error') or ''}".rstrip()
        )
    if r["status"] in {"unverified", "deeplink"}:
        pytest.skip("\n".join(lines))
    pytest.fail("\n".join(lines))
