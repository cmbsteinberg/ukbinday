"""Record cassettes for council modules from the live sites (never done by tests).

    uv run python -m scripts.councils.record hartlepool angus
    uv run python -m scripts.councils.record --all

Records each module's `meta.cases` (one sampled address when it has none). A case that errors, comes back empty or
doesn't replay keeps its previous cassette; an unchanged recording leaves the
file untouched. Exit status is 1 when any case failed.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from api.councils._base.discovery import load, module_names
from scripts.councils import cassette
from scripts.councils.check import _cases


async def record_module(name: str, sem: asyncio.Semaphore) -> list[str]:
    """Record one module's cases; returns the failures."""
    scraper = load(name)
    failed = []
    cases = _cases(scraper)
    # Modules without fixtures of their own get one sampled case.
    cases = [c for c in cases if c[1] == "fixture"] or [c for c in cases if c[1] == "sampled"][:1]
    for case_id, _source, params in cases:
        async with sem:
            try:
                recorded = await cassette.record(scraper, params)
            except Exception as exc:  # noqa: BLE001 - any failure keeps the old cassette
                print(f"  FAIL {name}/{case_id}: {type(exc).__name__}: {str(exc)[:200]}")
                failed.append(f"{name}/{case_id}")
                continue
        path = cassette.path_for(name, case_id)
        stale = path.exists() and not await cassette.still_replays(scraper, path)
        wrote = cassette.save(path, recorded, stale=stale)
        print(
            f"  {'wrote' if wrote else 'same '} {name}/{case_id} "
            f"({len(recorded.data['exchanges'])} exchanges, {len(recorded.data['golden'])} dates)"
        )
    return failed


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("modules", nargs="*")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--concurrency", type=int, default=4)
    args = ap.parse_args()
    names = module_names() if args.all else args.modules
    if not names:
        ap.error("name modules or pass --all")
    sem = asyncio.Semaphore(args.concurrency)
    failed = [f for fs in await asyncio.gather(*(record_module(n, sem) for n in names)) for f in fs]
    if failed:
        print("failed: " + " ".join(failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
