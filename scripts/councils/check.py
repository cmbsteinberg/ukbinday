"""Run council modules on their cases, against the live council sites.

Cases: the module's own `meta.cases`, plus the sampled addresses for its LADs
from tests/lad_test_cases.json.

    uv run python -m scripts.councils.check hartlepool adur_and_worthing
    uv run python -m scripts.councils.check --all --json /tmp/check.json

Exit status is 1 when any module has a case that errored.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import traceback
from pathlib import Path

from api.councils._base import Collection, Scraper, run
from api.councils._base.discovery import by_lad, load, module_names

ROOT = Path(__file__).resolve().parents[2]
LAD_CASES = ROOT / "tests" / "lad_test_cases.json"
TIMEOUT = 60


def _cases(scraper: Scraper) -> list[tuple[str, str, dict]]:
    """(case id, source, params) for the module's fixtures and its LADs' sampled addresses."""
    out = [(name, "fixture", dict(params)) for name, params in scraper.meta.cases.items()]
    lad_cases = json.loads(LAD_CASES.read_text())
    for lad in scraper.meta.lads:
        for case in lad_cases.get(lad, {}).get("cases", []):
            if case["source"] == "sampled":
                out.append((case["id"], "sampled", {k: v for k, v in case["params"].items() if v}))
    return out


def _summary(result: list[Collection] | BaseException) -> dict:
    if isinstance(result, BaseException):
        return {"outcome": "error", "error": f"{type(result).__name__}: {result}"[:400]}
    return {
        "outcome": "pass" if result else "empty",
        "count": len(result),
        "types": sorted({c.type for c in result}),
        "first": str(result[0].date) if result else None,
    }


async def _run(scraper: Scraper, params: dict) -> list[Collection] | BaseException:
    try:
        return await asyncio.wait_for(run(scraper, params), TIMEOUT)
    except Exception as exc:  # noqa: BLE001 - reporting any failure is the point
        exc.__traceback_text__ = "".join(traceback.format_exception(exc, limit=-4, chain=False))  # type: ignore[attr-defined]
        return exc


async def check_module(name: str, *, verbose: bool) -> dict:
    try:
        scraper = load(name)
    except Exception as exc:  # noqa: BLE001
        return {"module": name, "load_error": f"{type(exc).__name__}: {exc}", "cases": []}

    async def one(case_id: str, source: str, params: dict) -> dict:
        result = await _run(scraper, params)
        row = {"id": case_id, "source": source, **_summary(result)}
        if verbose and isinstance(result, BaseException):
            row["traceback"] = getattr(result, "__traceback_text__", "")
        return row

    rows = await asyncio.gather(*(one(*c) for c in _cases(scraper)))
    return {"module": name, "lads": list(scraper.meta.lads), "cases": list(rows)}


def _print(result: dict) -> None:
    if "load_error" in result:
        print(f"✗ {result['module']}: LOAD {result['load_error']}")
        return
    print(f"{result['module']} {result['lads']}")
    for row in result["cases"]:
        mark = {"pass": "✓", "empty": "∅", "error": "✗"}[row["outcome"]]
        print(f"  {mark} {row['id']:<22} {row.get('count', '')} {row.get('types') or row.get('error', '')}")
        if row.get("traceback"):
            print("      " + row["traceback"].replace("\n", "\n      "))


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("modules", nargs="*")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--json", type=Path, help="write results here")
    ap.add_argument("-v", "--verbose", action="store_true", help="show tracebacks")
    ap.add_argument("--concurrency", type=int, default=12)
    args = ap.parse_args()

    names = module_names() if args.all else args.modules
    if not names:
        ap.error("name modules or pass --all")
    by_lad({n: load(n) for n in names if _loads(n)})  # duplicate / unknown LAD claims fail loudly

    sem = asyncio.Semaphore(args.concurrency)

    async def guarded(name: str) -> dict:
        async with sem:
            result = await check_module(name, verbose=args.verbose)
            _print(result)
            return result

    results = await asyncio.gather(*(guarded(n) for n in names))
    if args.json:
        args.json.write_text(json.dumps(results, indent=1, default=str))
    failed = [r["module"] for r in results if "load_error" in r or any(c["outcome"] == "error" for c in r["cases"])]
    print(f"\n{len(results) - len(failed)}/{len(results)} modules without errors")
    if failed:
        print("errors: " + " ".join(failed))
    return 1 if failed else 0


def _loads(name: str) -> bool:
    try:
        load(name)
    except Exception:  # noqa: BLE001 - reported per module later
        return False
    return True


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
