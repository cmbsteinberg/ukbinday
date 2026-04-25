"""
Generate test cases for ukbcd (robbrad) scrapers from upstream input.json.

Reads input.json (synced from robbrad/UKBinCollectionData), matches entries
against the robbrad scrapers we actually have in api/scrapers/, extracts test
params, and merges them into tests/test_cases.json alongside the hacs entries.

Run after pipeline/hacs/generate_test_lookup.py so the hacs entries are
already in test_cases.json.
"""

import json
import logging
import re
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SCRAPERS_DIR = PROJECT_ROOT / "api" / "scrapers"
INPUT_JSON = PROJECT_ROOT / "pipeline" / "upstream" / "ukbcd" / "input.json"
OUTPUT_PATH = PROJECT_ROOT / "tests" / "test_cases.json"

# Params we can use for testing (skip web_driver, skip_get_url, etc.)
TEST_PARAMS = {"uprn", "postcode", "house_number", "usrn"}


def council_name_to_scraper_stem(council_name: str) -> str:
    """Convert CamelCase council name to our ukbcd_ snake_case filename stem."""
    return "ukbcd_" + re.sub(r"(?<!^)(?=[A-Z])", "_", council_name).lower()


def extract_test_params(data: dict) -> dict[str, str]:
    """Extract usable test params from an input.json entry."""
    params = {}
    for key in TEST_PARAMS:
        if key in data:
            params[key] = str(data[key])
    # input.json uses "paon" for house number in some entries
    if "paon" in data and "house_number" not in params:
        params["house_number"] = str(data["paon"])
    return params


def main():
    if not INPUT_JSON.exists():
        logger.error(
            "input.json not found at %s — run pipeline/ukbcd/sync.sh first", INPUT_JSON
        )
        return 1

    input_data = json.loads(INPUT_JSON.read_text())

    # Load existing test_cases.json (hacs entries), stripping stale robbrad entries
    existing: dict[str, list[dict]] = {}
    if OUTPUT_PATH.exists():
        existing = {
            k: v
            for k, v in json.loads(OUTPUT_PATH.read_text()).items()
            if not k.startswith("ukbcd_")
        }

    # Collect the set of robbrad scrapers we actually have
    our_scrapers = {p.stem for p in SCRAPERS_DIR.glob("ukbcd_*.py")}

    added = 0
    skipped_not_ours = 0
    skipped_no_params = 0

    for council_name, data in input_data.items():
        if not isinstance(data, dict):
            continue

        scraper_stem = council_name_to_scraper_stem(council_name)

        if scraper_stem not in our_scrapers:
            skipped_not_ours += 1
            continue

        params = extract_test_params(data)
        if not params:
            skipped_no_params += 1
            logger.warning("No usable test params for %s", scraper_stem)
            continue

        label = data.get("wiki_name", council_name)
        existing[scraper_stem] = [{"label": label, "params": params}]
        added += 1

    OUTPUT_PATH.write_text(json.dumps(existing, indent=2, sort_keys=True))
    logger.info("Wrote %d total scrapers to %s", len(existing), OUTPUT_PATH)

    print(f"\n{'=' * 50}")
    print("ukbcd Test Cases Summary")
    print(f"{'=' * 50}")
    print(f"Total in input.json:     {len(input_data)}")
    print(f"Added (in our subset):   {added}")
    print(f"Skipped (not our scraper): {skipped_not_ours}")
    print(f"Skipped (no test params):  {skipped_no_params}")
    print(f"Total in test_cases.json:  {len(existing)}")

    return 0


if __name__ == "__main__":
    rc = main()
    from pipeline.shared.enrich_test_postcodes import enrich
    enrich()
    sys.exit(rc)
