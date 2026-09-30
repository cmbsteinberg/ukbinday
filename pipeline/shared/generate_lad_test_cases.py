"""
Build tests/lad_test_cases.json: live test inputs keyed by LAD code.

The unit under test is the *council* a user lands on (LAD -> scraper via
api/data/lad_lookup.json), not the scraper file. For every wired LAD this
emits:

  sampled   Real addresses drawn from ONS data and resolved through the same
            address API the frontend uses. A postcode is picked from ONSUD
            (restricted to the LAD via ONSPD and to postcodes with 4-60 UPRNs,
            which screens out single-occupier commercial postcodes), then
            /addresses supplies the UPRN plus the text fields the frontend
            sends (address, house_number, street). Only addresses whose UPRN
            is also in ONSUD for that postcode and whose first line is a plain
            house number are kept, a proxy for "domestic" since neither
            source carries a classification. Params mirror api/static/app.js
            exactly, so a pass means a real user could get a schedule.
  fixture   The scraper's upstream TEST_CASES rows (from tests/test_cases.json),
            kept as a fallback. They cover scrapers that need council-internal
            ids (property_id, usrn, ...) the frontend cannot supply.
  blind     Optional (--blind N): ONSUD uprn+postcode with no address API
            filtering. Only useful to measure how often a raw ONS UPRN is
            unknown to the council.

Refresh policy (sticky, run monthly): the existing file is the starting
point. A sampled case is kept unless its outcome in the last
tests/output/lad_integration_output.json was input_rejected or empty (the
address, not the scraper, is the likely problem); dropped cases are replaced
from postcodes the LAD hasn't used yet. LADs that are new, or whose
scraper_id changed, are sampled afresh. Fixture rows are always re-read from
tests/test_cases.json. --resample-all ignores the existing file.

Selection is deterministic: every choice is ordered by md5(seed || key), so a
given seed plus the same ONS edition and address API answers reproduces the
file. Bump --seed with --resample-all to rotate every address.

Usage:
    uv run python -m pipeline.shared.generate_lad_test_cases               # sticky refresh
    uv run python -m pipeline.shared.generate_lad_test_cases --resample-all
    uv run python -m pipeline.shared.generate_lad_test_cases --lads E06000001,S12000036 --blind 2
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import os
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)
logging.getLogger("httpx").setLevel(logging.WARNING)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
OUTPUT_PATH = PROJECT_ROOT / "tests" / "lad_test_cases.json"
FIXTURES_PATH = PROJECT_ROOT / "tests" / "test_cases.json"
LAD_LOOKUP_PATH = PROJECT_ROOT / "api" / "data" / "lad_lookup.json"
RESULTS_PATH = PROJECT_ROOT / "tests" / "output" / "lad_integration_output.json"
ONSUD_PATH = PROJECT_ROOT / "pipeline" / "data" / "onsud_uprn_postcode.parquet"
ONSPD_PATH = PROJECT_ROOT / "pipeline" / "data" / "onspd_postcode_lad.parquet"

DEFAULT_SEED = "2026-09"
CANDIDATE_POSTCODES = 10
MIN_UPRNS, MAX_UPRNS = 4, 60

# Params the frontend can supply (path uprn + query string built in app.js).
FRONTEND_PARAMS = {"uprn", "postcode", "address", "house_number", "street"}

_PLAIN_NUMBER = re.compile(r"^\d+[A-Za-z]?$")
_NON_DOMESTIC = re.compile(
    r"\b(ltd|limited|plc|llp|school|academy|college|church|chapel|surgery|"
    r"practice|clinic|hospital|hotel|inn|pub|bar|club|council|office|offices|"
    r"centre|center|garage|farm|depot|works|unit|store|shop|stores|bank|"
    r"station|hall|library|nursery|pharmacy|restaurant|cafe)\b",
    re.IGNORECASE,
)


def _rank(seed: str, key: object) -> str:
    return hashlib.md5(f"{seed}|{key}".encode()).hexdigest()


def _candidate_postcodes(lads: list[str], seed: str, k: int) -> dict[str, list[tuple[str, list[int]]]]:
    """Per LAD, k postcodes (with their ONSUD UPRNs) in deterministic order."""
    import duckdb

    con = duckdb.connect()
    con.execute("CREATE TEMP TABLE want (lad VARCHAR)")
    con.executemany("INSERT INTO want VALUES (?)", [(x,) for x in lads])
    rows = con.execute(
        f"""
        WITH pc AS (
            SELECT TRIM(u.postcode) AS postcode, s.lad_code AS lad,
                   list(u.uprn ORDER BY u.uprn) AS uprns, count(*) AS n
            FROM read_parquet(?) u
            JOIN read_parquet(?) s ON REPLACE(TRIM(u.postcode), ' ', '') = s.postcode
            JOIN want w ON w.lad = s.lad_code
            GROUP BY 1, 2
        ), ranked AS (
            SELECT *, row_number() OVER (
                PARTITION BY lad ORDER BY md5(? || '|' || postcode)) AS rk
            FROM pc WHERE n BETWEEN {MIN_UPRNS} AND {MAX_UPRNS}
        )
        SELECT lad, postcode, uprns FROM ranked WHERE rk <= ? ORDER BY lad, rk
        """,
        [str(ONSUD_PATH), str(ONSPD_PATH), seed, k],
    ).fetchall()
    out: dict[str, list[tuple[str, list[int]]]] = {}
    for lad, postcode, uprns in rows:
        out.setdefault(lad, []).append((postcode, list(uprns)))

    # ONSUD is GB-only, so Northern Ireland has no UPRN rows. Fall back to
    # ONSPD postcodes (which do cover BT) with no UPRN cross-check; ONSPD
    # stores them unspaced, so re-insert the space before the inward code.
    missing = [lad for lad in lads if lad not in out]
    if missing:
        con.execute("DELETE FROM want")
        con.executemany("INSERT INTO want VALUES (?)", [(x,) for x in missing])
        rows = con.execute(
            """
            SELECT lad, postcode FROM (
                SELECT s.lad_code AS lad, s.postcode, row_number() OVER (
                    PARTITION BY s.lad_code ORDER BY md5(? || '|' || s.postcode)) AS rk
                FROM read_parquet(?) s JOIN want w ON w.lad = s.lad_code
            ) WHERE rk <= ? ORDER BY lad, rk
            """,
            [seed, str(ONSPD_PATH), k * 2],
        ).fetchall()
        for lad, pc in rows:
            out.setdefault(lad, []).append((f"{pc[:-3]} {pc[-3:]}", []))
    con.close()
    return out


def _is_domestic(addr: dict) -> bool:
    house = (addr.get("house_number_or_name") or "").strip()
    return bool(
        _PLAIN_NUMBER.match(house)
        and addr.get("street")
        and not _NON_DOMESTIC.search(addr.get("full_address") or "")
    )


def _sampled_case(lad: str, i: int, addr: dict) -> dict:
    params = {
        "uprn": str(addr["uprn"]),
        "postcode": addr["postcode"],
        "address": addr["full_address"],
        "house_number": addr["house_number_or_name"],
        "street": addr["street"],
    }
    return {"id": f"{lad}-s{i}", "source": "sampled", "label": addr["full_address"], "params": params}


async def _sample_via_address_api(
    lad: str,
    candidates: list[tuple[str, list[int]]],
    n: int,
    seed: str,
    sem: asyncio.Semaphore,
    avoid_postcodes: set[str] = frozenset(),
    first_index: int = 1,
) -> tuple[list[dict], list[str]]:
    """Up to n new sampled cases, one per postcode, skipping postcodes already
    used (kept or dropped) so a resample moves to a different street."""
    from api.services.address_lookup import search_addresses

    cases: list[dict] = []
    notes: list[str] = []
    errors = 0
    for postcode, onsud_uprns in candidates:
        if len(cases) >= n:
            break
        if postcode in avoid_postcodes:
            continue
        addrs = None
        for attempt in range(3):
            async with sem:
                try:
                    addrs = await search_addresses(postcode)
                    # The API intermittently answers [] for postcodes it knows
                    # (observed 2026-09-30: same postcode 18, 0, 18 results)
                    if addrs:
                        break
                    addrs = None
                except Exception as exc:  # noqa: BLE001 - retried, then the postcode is skipped
                    logger.debug("address API failed for %s: %s", postcode, exc)
            await asyncio.sleep(1 + 2 * attempt)
        if addrs is None:
            # Skipping changes which postcode gets used, so it breaks
            # reproducibility; the note makes that visible in the diff.
            errors += 1
            continue
        known = set(onsud_uprns)
        pool = [
            a for a in addrs
            if _is_domestic(a) and (not known or int(a["uprn"]) in known)
        ]
        if not pool:
            continue
        pick = min(pool, key=lambda a: _rank(seed, a["uprn"]))
        cases.append(_sampled_case(lad, first_index + len(cases), pick))
    if errors:
        notes.append(f"address API failed for {errors} postcode(s)")
    if len(cases) < n:
        notes.append(f"only {len(cases)}/{n} domestic addresses in {len(candidates)} candidate postcodes")
    return cases, notes


def _blind_cases(
    lad: str, candidates: list[tuple[str, list[int]]], n: int, seed: str, exclude: set[str] = frozenset()
) -> list[dict]:
    out = []
    for postcode, uprns in candidates:
        if len(out) >= n:
            break
        pool = [u for u in uprns if str(u) not in exclude]
        if not pool:
            continue
        uprn = min(pool, key=lambda u: _rank(seed, u))
        out.append(
            {
                "id": f"{lad}-b{len(out) + 1}",
                "source": "blind",
                "label": f"ONSUD {uprn} {postcode}",
                "params": {"uprn": str(uprn), "postcode": postcode},
            }
        )
    return out


def _fixture_cases(lad: str, rows: list[dict]) -> list[dict]:
    return [
        {"id": f"{lad}-f{i}", "source": "fixture", "label": r["label"], "params": dict(r["params"])}
        for i, r in enumerate(rows, 1)
    ]


def _registry_required() -> dict[str, list[str]]:
    import logging as _logging

    from api.services.scraper_registry import ScraperRegistry

    _logging.getLogger("api").setLevel(_logging.ERROR)
    return {m.id: m.required_params for m in ScraperRegistry.build().list_all()}


# Last outcomes that mean the address itself is the likely problem (the
# council doesn't know it, or it has no service). Any other outcome - a pass,
# or a failure that is the scraper's or the network's fault - keeps the
# address, so a broken scraper stays tested on the same inputs until fixed.
RESAMPLE_OUTCOMES = {"input_rejected", "empty"}


def _last_outcomes(results_path: Path) -> dict[tuple[str, str, str], str]:
    """(LAD, case id, uprn) -> outcome of sampled cases in the last test run."""
    if not results_path.exists():
        return {}
    lads = json.loads(results_path.read_text()).get("lads", {})
    return {
        (code, c["id"], str(c.get("uprn"))): c["outcome"]
        for code, e in lads.items()
        for c in e.get("cases", [])
        if c.get("source") == "sampled"
    }


async def build(
    lads_filter: set[str] | None,
    per_lad: int,
    blind: int,
    seed: str,
    offline: bool,
    previous: dict,
    last_outcomes: dict[tuple[str, str, str], str],
) -> tuple[dict, dict[str, int]]:
    """previous: the existing lad_test_cases.json ({} for a full resample)."""
    lad_lookup = json.loads(LAD_LOOKUP_PATH.read_text())
    fixtures = json.loads(FIXTURES_PATH.read_text()) if FIXTURES_PATH.exists() else {}
    required = _registry_required()

    wired = {
        code: info
        for code, info in sorted(lad_lookup.items())
        if info.get("scraper_id") and (not lads_filter or code in lads_filter)
    }
    candidates = _candidate_postcodes(list(wired), seed, max(CANDIDATE_POSTCODES, blind))
    sem = asyncio.Semaphore(6)
    stats = {"kept": 0, "dropped": 0, "new": 0, "fresh_lads": 0}

    async def one(code: str, info: dict) -> tuple[str, dict]:
        sid = info["scraper_id"]
        unmet = sorted(set(required.get(sid, [])) - FRONTEND_PARAMS)
        entry: dict = {"name": info.get("name"), "scraper_id": sid, "cases": [], "notes": []}
        if unmet:
            entry["fixture_only"] = True
        cands = candidates.get(code, [])

        prev = previous.get(code)
        same_scraper = bool(prev) and prev.get("scraper_id") == sid
        if previous and not same_scraper:
            stats["fresh_lads"] += 1
        prev_sampled = [c for c in prev["cases"] if c["source"] == "sampled"] if same_scraper else []
        kept = [c for c in prev_sampled if last_outcomes.get((code, c["id"], c["params"]["uprn"])) not in RESAMPLE_OUTCOMES]
        stats["kept"] += len(kept)
        stats["dropped"] += len(prev_sampled) - len(kept)

        if sid not in required:
            entry["notes"].append("scraper not loadable by registry")
        if unmet:
            entry["notes"].append(f"fixture-only: frontend cannot supply required {unmet}")
        elif not cands:
            entry["notes"].append("no ONSUD postcodes for LAD")
        elif offline:
            entry["cases"] += [dict(c, source="blind") for c in _blind_cases(code, cands, per_lad, seed)]
        else:
            entry["cases"] += kept
            need = per_lad - len(kept)
            if need > 0:
                used = {c["params"]["postcode"] for c in prev_sampled}
                next_index = 1 + max((int(c["id"].rsplit("-s", 1)[1]) for c in prev_sampled), default=0)
                cases, notes = await _sample_via_address_api(
                    code, cands, need, seed, sem, avoid_postcodes=used, first_index=next_index
                )
                stats["new"] += len(cases)
                entry["cases"] += cases
                entry["notes"] += notes
        if blind and cands and not offline:
            taken = {c["params"]["uprn"] for c in entry["cases"]}
            entry["cases"] += _blind_cases(code, cands, blind, seed, taken)
        entry["cases"] += _fixture_cases(code, fixtures.get(sid, []))
        if not entry["notes"]:
            del entry["notes"]
        return code, entry

    results = await asyncio.gather(*(one(c, i) for c, i in wired.items()))
    return {
        "_meta": {
            "schema": 1,
            "seed": seed,
            "per_lad": per_lad,
            "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "sampling": "offline (ONSUD only)" if offline else "ONSUD postcode -> address API",
        },
        **dict(results),
    }, stats


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--lads", help="comma-separated LAD codes (default: all wired)")
    ap.add_argument("--per-lad", type=int, default=2, help="sampled addresses per LAD")
    ap.add_argument("--blind", type=int, default=0, help="extra raw-ONSUD cases per LAD (diagnostic)")
    ap.add_argument("--seed", default=DEFAULT_SEED)
    ap.add_argument("--offline", action="store_true", help="skip the address API; raw ONSUD uprn+postcode only")
    ap.add_argument("--output", type=Path, default=OUTPUT_PATH)
    ap.add_argument(
        "--resample-all",
        action="store_true",
        help="ignore the existing file and last results; sample every LAD afresh",
    )
    ap.add_argument(
        "--results",
        type=Path,
        default=RESULTS_PATH,
        help="last test_lad_integration output, read to decide what to resample",
    )
    args = ap.parse_args(argv)

    # Same defaults tests/conftest.py uses; must be set before api.config loads
    os.environ.setdefault("ADDRESS_API_URL", "https://www.midsuffolk.gov.uk/api/jsonws/invoke")
    os.environ.setdefault("ADDRESS_API_COMPANY_ID", "1486681")

    lads = set(args.lads.split(",")) if args.lads else None
    sticky = not args.resample_all and args.output.exists()
    previous = json.loads(args.output.read_text()) if sticky else {}
    last = _last_outcomes(args.results) if sticky else {}
    if sticky and not last:
        logger.warning("No results at %s: keeping every existing sampled case", args.results)
    data, stats = asyncio.run(
        build(lads, args.per_lad, args.blind, args.seed, args.offline, previous, last)
    )
    logger.info(
        "%s: kept %d sampled cases, dropped %d (last outcome %s), sampled %d new; %d LADs new or rewired",
        "sticky" if sticky else "full resample",
        stats["kept"],
        stats["dropped"],
        "/".join(sorted(RESAMPLE_OUTCOMES)),
        stats["new"],
        stats["fresh_lads"],
    )
    if lads and args.output.exists():
        # A --lads run only touches those LADs
        existing = json.loads(args.output.read_text())
        existing.update(data)
        data = existing
    args.output.write_text(json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n")

    lad_entries = {k: v for k, v in data.items() if not k.startswith("_")}
    by_source: dict[str, int] = {}
    for e in lad_entries.values():
        for c in e["cases"]:
            by_source[c["source"]] = by_source.get(c["source"], 0) + 1
    no_sampled = [k for k, e in lad_entries.items() if not any(c["source"] == "sampled" for c in e["cases"])]
    no_cases = [k for k, e in lad_entries.items() if not e["cases"]]
    logger.info("Wrote %d LADs to %s: %s", len(lad_entries), args.output, by_source)
    logger.info("LADs without a sampled case: %d %s", len(no_sampled), no_sampled[:40])
    logger.info("LADs with no cases at all: %d %s", len(no_cases), no_cases)
    return 0


if __name__ == "__main__":
    sys.exit(main())
