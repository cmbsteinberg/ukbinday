"""Probe a remote deployment with the sampled live-test cases and diff against the last local run.

Requests from a Vercel function leave from AWS London, not the machine that
produced tests/output/lad_integration_output.json. A council that blocks AWS
ranges passes locally and fails from there. This runs the same cases through
the deployment's `GET /api/v2/{lad}/view/{uprn}` and lists the councils whose
status got worse.

Usage:
    uv run python -m scripts.vercel_probe --base-url https://<preview>.vercel.app
    uv run python -m scripts.vercel_probe --base-url https://<preview>.vercel.app \\
        --lad E06000001,E08000035 --concurrency 4 --json /tmp/probe.json

Leave TURNSTILE_SECRET unset on the preview, or the route will refuse the
requests. If the preview sits behind Vercel Deployment Protection, pass
--bypass-secret (or set VERCEL_AUTOMATION_BYPASS_SECRET).

What it does:
  * Cases come from tests/lad_test_cases.json and are sent exactly as the live
    test sends them (scripts/lad_cases.py: same params, same response
    classification, including the 200 fallback deeplink keyed on the
    X-Scrape-Failure header). By default only the cases that decide a LAD's
    status run: sampled ones, or fixture ones for `fixture_only` LADs.
    --all-sources runs the fixture cases of other LADs too.
  * Jobs dedupe on the cases file's scraper_id; failures are retried once at
    low concurrency (like the live test).
  * The live test tells `unreachable` (this machine can't reach the host) from
    `upstream_error` with a local host probe. There is no such probe from here,
    and hiding an AWS block as "unverified" would defeat the point, so a
    network or timeout failure reported by the deployment counts as
    `upstream_error`, which scripts/lad_status.py reads as broken. The raw
    failure is kept in each case as `failure`.
  * A LAD's status comes from scripts/lad_status.py, so "working" means what
    it means in the live test. It is compared with the status in
    tests/output/lad_integration_output.json (--baseline to use another file).

  * Production answers /view from its calendar cache, which would report a
    council as working for as long as its cached data lasts. --cron-secret
    (env CRON_SECRET) sends `fresh=1` with the secret, so every case is a
    live scrape that neither reads nor writes the cache.

Output: regressions (working locally, not from the deployment) with each
case's outcome, improvements, and a count of the unchanged. Exit code 1 if
there are any regressions. --json writes the full per-LAD results.
--write-output replaces tests/output/lad_integration_output.json with this
run, in the live test's shape, so ./pipeline/ci/post_integration.sh builds
the flags, coverage map, badge and sankey from production (the Coverage
workflow does this weekly); the exit code is then 0.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import httpx

from scripts.lad_cases import (
    DEFAULT_CASES_PATH,
    FINAL_OUTCOMES,
    NETWORKISH,
    job_key,
    load_lads,
    view,
)
from scripts.lad_status import LAD_OUTPUT_PATH, deciding_cases, lad_status

DEFAULT_CONCURRENCY = 8
RETRY_CONCURRENCY = 4
REQUEST_TIMEOUT = 60  # the deployment enforces its own 30 s SCRAPER_TIMEOUT inside this


def _remote_outcome(result: dict) -> dict:
    """No local host probe is possible, so a site failure is an upstream_error."""
    if result["outcome"] in NETWORKISH:
        return {**result, "failure": result["outcome"], "outcome": "upstream_error"}
    if result["outcome"] == "lock_contention":
        return {**result, "failure": "lock_contention", "outcome": "upstream_error"}
    return result


async def probe(
    base_url: str,
    lads: dict[str, dict],
    concurrency: int,
    bypass_secret: str | None = None,
    log=lambda _msg: None,
    cron_secret: str | None = None,
) -> dict[str, dict]:
    """LAD code -> {name, scraper_id, fixture_only, status, reason, passed_sources, cases} for the deployment."""
    headers = {"x-vercel-protection-bypass": bypass_secret} if bypass_secret else {}
    if cron_secret:
        headers["Authorization"] = f"Bearer {cron_secret}"
    jobs: dict[str, tuple[str, dict]] = {}
    for code, entry in lads.items():
        for case in entry["cases"]:
            jobs.setdefault(job_key(entry["scraper_id"], case["params"]), (code, case["params"]))

    async with httpx.AsyncClient(
        base_url=base_url.rstrip("/") + "/api/v2", timeout=REQUEST_TIMEOUT, headers=headers,
        params={"fresh": "1"} if cron_secret else None, follow_redirects=True,
    ) as client:
        done = 0

        async def run(key: str, sem: asyncio.Semaphore) -> tuple[str, dict]:
            nonlocal done
            council, params = jobs[key]
            async with sem:
                result = await view(client, council, params)
            done += 1
            log(f"\r  {done}/{len(jobs)} requests")
            return key, result

        sem = asyncio.Semaphore(concurrency)
        results = dict(await asyncio.gather(*(run(k, sem) for k in jobs)))
        retry = [k for k, r in results.items() if r["outcome"] not in FINAL_OUTCOMES]
        if retry:
            log(f"\n  retrying {len(retry)} failed request(s) at concurrency {RETRY_CONCURRENCY}\n")
            done, rsem = 0, asyncio.Semaphore(RETRY_CONCURRENCY)
            for key, r in await asyncio.gather(*(run(k, rsem) for k in retry)):
                r["attempts"] = 2
                r["first_attempt"] = results[key]["outcome"]
                results[key] = r
        log("\n")

    out: dict[str, dict] = {}
    for code, entry in lads.items():
        cases = []
        for case in entry["cases"]:
            r = _remote_outcome(results[job_key(entry["scraper_id"], case["params"])])
            cases.append(
                {"id": case["id"], "source": case["source"], "label": case.get("label"), "uprn": case["params"].get("uprn"), **r}
            )
        fixture_only = bool(entry.get("fixture_only"))
        status, reason = lad_status(cases, fixture_only)
        out[code] = {
            "name": entry.get("name"),
            "scraper_id": entry["scraper_id"],
            "fixture_only": fixture_only,
            "status": status,
            "reason": reason,
            "passed_sources": sorted({c["source"] for c in cases if c["outcome"] == "pass"}),
            "cases": cases,
        }
    return out


def write_output(remote: dict[str, dict], path: Path, meta: dict) -> None:
    """This run as the live test's output file (meta, summary, lads)."""
    summary = {
        "lads": len(remote),
        "status": dict(Counter(r["status"] for r in remote.values())),
        "outcomes_by_source": {
            s: dict(Counter(c["outcome"] for r in remote.values() for c in r["cases"] if c["source"] == s))
            for s in ("sampled", "fixture")
        },
        "passed_sources": dict(Counter("+".join(r["passed_sources"]) or "-" for r in remote.values())),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"meta": meta, "summary": summary, "lads": dict(sorted(remote.items()))}, indent=2, default=str)
        + "\n"
    )


def diff(remote: dict[str, dict], baseline: dict[str, dict]) -> dict[str, list[str]]:
    """Group LAD codes: regressions, improvements, unchanged, no_baseline, undecided."""
    groups: dict[str, list[str]] = {k: [] for k in ("regressions", "improvements", "unchanged", "no_baseline", "undecided")}
    for code, r in remote.items():
        if r["status"] == "unverified":  # no deciding case ran, so nothing to compare
            groups["undecided"].append(code)
        elif code not in baseline:
            groups["no_baseline"].append(code)
        else:
            was, now = baseline[code]["status"] == "working", r["status"] == "working"
            groups["regressions" if was and not now else "improvements" if now and not was else "unchanged"].append(code)
    return groups


def _case_line(c: dict) -> str:
    detail = c.get("failure") or ""
    bits = [f"status={c.get('status_code')}", f"{c.get('elapsed_s')}s"]
    if detail:
        bits.append(f"failure={detail}")
    if c.get("error"):
        bits.append(str(c["error"])[:120])
    return f"      [{c['source']}] {c['outcome']:<15} uprn={c.get('uprn')} " + " ".join(bits)


def _print_lad(code: str, r: dict, baseline: dict[str, dict]) -> None:
    was = baseline.get(code, {}).get("status", "-")
    why = f" ({r['reason']})" if r["reason"] else ""
    print(f"  {code} {r['name']} [{r['scraper_id']}]: local {was} -> deployment {r['status']}{why}")
    for c in deciding_cases(r["cases"], r["fixture_only"]):
        print(_case_line(c))


def report(remote: dict[str, dict], baseline: dict[str, dict], groups: dict[str, list[str]]) -> None:
    print(f"\nRegressions (working locally, not from the deployment): {len(groups['regressions'])}")
    for code in groups["regressions"]:
        _print_lad(code, remote[code], baseline)
    print(f"\nImprovements (not working locally, working from the deployment): {len(groups['improvements'])}")
    for code in groups["improvements"]:
        _print_lad(code, remote[code], baseline)
    outcomes = Counter(c["outcome"] for r in remote.values() for c in deciding_cases(r["cases"], r["fixture_only"]))
    print(f"\nUnchanged: {len(groups['unchanged'])}")
    if groups["no_baseline"]:
        print(f"No local baseline: {', '.join(groups['no_baseline'])}")
    if groups["undecided"]:
        print(f"No deciding case ran: {', '.join(groups['undecided'])}")
    print(f"Deployment status: {dict(Counter(r['status'] for r in remote.values()))}")
    print(f"Deciding case outcomes: {dict(outcomes)}")


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Run the sampled live-test cases against a deployment and diff against the last local run.")
    p.add_argument("--base-url", required=True, help="deployment origin, e.g. https://<preview>.vercel.app")
    p.add_argument("--lad", default="", help="comma-separated LAD codes to run (default: all)")
    p.add_argument("--concurrency", type=int, default=DEFAULT_CONCURRENCY)
    p.add_argument("--json", type=Path, dest="json_out", help="write full per-LAD results here")
    p.add_argument("--all-sources", action="store_true", help="also run fixture cases for LADs decided by sampled ones")
    p.add_argument("--cases", type=Path, default=DEFAULT_CASES_PATH)
    p.add_argument("--baseline", type=Path, default=LAD_OUTPUT_PATH, help="last local run to diff against")
    p.add_argument(
        "--bypass-secret",
        default=os.environ.get("VERCEL_AUTOMATION_BYPASS_SECRET"),
        help="Vercel Deployment Protection bypass secret (env VERCEL_AUTOMATION_BYPASS_SECRET)",
    )
    p.add_argument(
        "--cron-secret",
        default=os.environ.get("CRON_SECRET"),
        help="the deployment's CRON_SECRET (env CRON_SECRET): scrape live, past the calendar cache",
    )
    p.add_argument("--write-output", action="store_true", help=f"replace {LAD_OUTPUT_PATH.name} with this run")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    lads = load_lads(args.cases, codes={c.strip() for c in args.lad.split(",") if c.strip()})
    if not args.all_sources:
        lads = {c: {**e, "cases": deciding_cases(e["cases"], bool(e.get("fixture_only")))} for c, e in lads.items()}
    if not lads:
        print(f"no LAD cases found in {args.cases}", file=sys.stderr)
        return 2
    if not args.baseline.exists():
        print(f"no baseline at {args.baseline}", file=sys.stderr)
        return 2
    baseline = json.loads(args.baseline.read_text()).get("lads", {})

    print(f"Probing {args.base_url}: {len(lads)} LADs, concurrency {args.concurrency}")
    started, t0 = datetime.now(UTC), time.monotonic()
    remote = asyncio.run(
        probe(
            args.base_url, lads, args.concurrency, args.bypass_secret,
            log=lambda m: print(m, end="", file=sys.stderr), cron_secret=args.cron_secret,
        )
    )
    groups = diff(remote, baseline)
    report(remote, baseline, groups)

    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(
            json.dumps(
                {
                    "meta": {
                        "base_url": args.base_url,
                        "started_at": started.isoformat(timespec="seconds"),
                        "wall_clock_s": round(time.monotonic() - t0, 1),
                        "baseline": str(args.baseline),
                    },
                    "diff": groups,
                    "lads": {c: {**r, "baseline_status": baseline.get(c, {}).get("status")} for c, r in remote.items()},
                },
                indent=2,
                default=str,
            )
            + "\n"
        )
        print(f"\nWrote {args.json_out}")
    if args.write_output:
        write_output(
            remote,
            LAD_OUTPUT_PATH,
            {
                "started_at": started.isoformat(timespec="seconds"),
                "wall_clock_s": round(time.monotonic() - t0, 1),
                "base_url": args.base_url,
                "cases_file": str(args.cases),
                "fresh": bool(args.cron_secret),
                "partial": bool(args.lad),
                "lads_run": sorted(remote) if args.lad else "all",
            },
        )
        print(f"Wrote {LAD_OUTPUT_PATH}")
        return 0
    return 1 if groups["regressions"] else 0


if __name__ == "__main__":
    sys.exit(main())
