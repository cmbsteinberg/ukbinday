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


def enrich():
    if not PARQUET_PATH.exists():
        logger.warning("UPRN-postcode parquet not found at %s — skipping enrichment", PARQUET_PATH)
        return

    test_cases = json.loads(OUTPUT_PATH.read_text())

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
