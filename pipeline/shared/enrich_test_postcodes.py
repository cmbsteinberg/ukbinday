"""
Enrich test_cases.json with postcodes looked up from the ONSUD UPRN-postcode
parquet file. Adds a `postcode` field to any test case that has a `uprn` but
no `postcode`.

Called automatically at the end of both generate_test_lookup scripts.
Can also be run standalone: python -m pipeline.shared.enrich_test_postcodes
"""

import json
import logging
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
OUTPUT_PATH = PROJECT_ROOT / "tests" / "test_cases.json"
PARQUET_PATH = PROJECT_ROOT / "pipeline" / "data" / "onsud_uprn_postcode.parquet"
ONSPD_PARQUET_PATH = PROJECT_ROOT / "pipeline" / "data" / "onspd_postcode_lad.parquet"
LAD_LOOKUP_PATH = PROJECT_ROOT / "api" / "data" / "lad_lookup.json"

# Scraper IDs whose upstream UPRN fixtures go stale. On every generation run
# their UPRN+postcode pairs are resampled deterministically from the
# ONSUD/ONSPD join instead of being hand-edited.
RESAMPLE_SCRAPERS = [
    "hacs_bedford_gov_uk",
    "hacs_eastherts_gov_uk",
    "hacs_enfield_gov_uk",
    "hacs_harlow_gov_uk",
    "hacs_kirklees_gov_uk",
    "hacs_reigatebanstead_gov_uk",
    "hacs_st_helens_gov_uk",
]


def _scraper_lad_map() -> dict:
    """Invert lad_lookup.json (LAD code -> scraper_id) to scraper_id -> LAD."""
    try:
        lad_lookup = json.loads(LAD_LOOKUP_PATH.read_text())
    except (OSError, ValueError):
        return {}
    return {
        v.get("scraper_id"): lad
        for lad, v in lad_lookup.items()
        if isinstance(v, dict) and v.get("scraper_id")
    }


def _sample_uprns_for_lad(lad_code: str, n: int) -> list:
    """Return n deterministic fresh (uprn, postcode) pairs for a LAD."""
    import duckdb

    con = duckdb.connect()
    try:
        rows = con.execute(
            """
            SELECT u.uprn, u.postcode
            FROM read_parquet(?) u
            JOIN read_parquet(?) s
              ON REPLACE(TRIM(u.postcode), ' ', '') = s.postcode
            WHERE s.lad_code = ?
            ORDER BY md5(u.uprn::VARCHAR)
            LIMIT ?
            """,
            [str(PARQUET_PATH), str(ONSPD_PARQUET_PATH), lad_code, n],
        ).fetchall()
    finally:
        con.close()
    return [(int(uprn), str(postcode).strip()) for uprn, postcode in rows]


def resample_stale_uprns(test_cases: dict) -> int:
    """Replace stale UPRN+postcode pairs for RESAMPLE_SCRAPERS from ONS data.

    Only entries that already carry a `uprn` param are touched, and only when
    `uprn`+`postcode` are the sole params: sibling address params
    (house_number, street, usrn, ...) identify a specific property and must
    not be mixed with a freshly sampled pair, so those entries are skipped.
    A leading-zero padded UPRN keeps its width via zfill. Returns the number
    replaced.
    """
    if not PARQUET_PATH.exists() or not ONSPD_PARQUET_PATH.exists():
        logger.warning("ONS parquet missing — skipping UPRN resample")
        return 0
    lad_map = _scraper_lad_map()
    replaced = 0
    for scraper_id in RESAMPLE_SCRAPERS:
        entries = test_cases.get(scraper_id)
        if not entries:
            continue
        lad_code = lad_map.get(scraper_id)
        if not lad_code:
            logger.warning("No LAD code for %s — skipping resample", scraper_id)
            continue
        idx = [
            i
            for i, e in enumerate(entries)
            if e.get("params", {}).get("uprn", "").strip()
            and set(e["params"]) <= {"uprn", "postcode"}
        ]
        if not idx:
            continue
        fresh = _sample_uprns_for_lad(lad_code, len(idx))
        if len(fresh) < len(idx):
            logger.warning("Only %d ONS samples for %s — skipping", len(fresh), scraper_id)
            continue
        for i, (uprn_new, postcode_new) in zip(idx, fresh):
            old_uprn = entries[i]["params"]["uprn"].strip()
            width = len(old_uprn) if old_uprn.startswith("0") else 0
            entries[i]["params"]["uprn"] = (
                str(uprn_new).zfill(width) if width else str(uprn_new)
            )
            entries[i]["params"]["postcode"] = postcode_new
            replaced += 1
    if replaced:
        logger.info("Resampled %d stale UPRNs from ONS data", replaced)
    return replaced


def enrich():
    if not PARQUET_PATH.exists():
        logger.warning("UPRN-postcode parquet not found at %s — skipping enrichment", PARQUET_PATH)
        return

    test_cases = json.loads(OUTPUT_PATH.read_text())

    resample_stale_uprns(test_cases)

    uprns_needed: set[int] = set()
    for entries in test_cases.values():
        for entry in entries:
            p = entry["params"]
            uprn_raw = p.get("uprn", "").strip().lstrip("0")
            if uprn_raw and not p.get("postcode", "").strip():
                try:
                    uprns_needed.add(int(uprn_raw))
                except ValueError:
                    pass

    if not uprns_needed:
        logger.info("All test cases already have postcodes — nothing to enrich")
        return

    import duckdb

    con = duckdb.connect()
    uprn_list = list(uprns_needed)
    con.execute("CREATE TEMP TABLE wanted (uprn BIGINT)")
    con.executemany("INSERT INTO wanted VALUES (?)", [(u,) for u in uprn_list])

    rows = con.execute(
        """
        SELECT w.uprn, p.postcode
        FROM wanted w
        JOIN read_parquet(?) p ON w.uprn = p.uprn
        """,
        [str(PARQUET_PATH)],
    ).fetchall()
    lookup = {uprn: pc for uprn, pc in rows}
    con.close()

    enriched = 0
    for entries in test_cases.values():
        for entry in entries:
            p = entry["params"]
            uprn_raw = p.get("uprn", "").strip().lstrip("0")
            if uprn_raw and not p.get("postcode", "").strip():
                try:
                    pc = lookup.get(int(uprn_raw))
                except ValueError:
                    continue
                if pc:
                    p["postcode"] = pc
                    enriched += 1

    OUTPUT_PATH.write_text(json.dumps(test_cases, indent=2, sort_keys=True))
    logger.info(
        "Enriched %d test cases with postcodes (%d UPRNs not found in ONSUD)",
        enriched,
        len(uprns_needed) - len(lookup),
    )


if __name__ == "__main__":
    enrich()
    sys.exit(0)
