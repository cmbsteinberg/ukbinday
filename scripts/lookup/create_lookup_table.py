import json
import logging
import re
from pathlib import Path
from urllib.parse import urlparse

import httpx
import ibis

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

ONS_URL = "https://hub.arcgis.com/api/v3/datasets/7efd49be24fb4ed8b21eedeb2540ea8c_0/downloads/data?format=csv&spatialRefId=4326&where=1%3D1"
INPUT_JSON_URL = "https://raw.githubusercontent.com/robbrad/UKBinCollectionData/master/uk_bin_collection/tests/input.json"

ROOT_DIR = Path(__file__).parent.parent.parent
DATA_DIR = ROOT_DIR / "api" / "data"
SCRAPER_LOOKUP_PATH = DATA_DIR / "admin_scraper_lookup.json"
POSTCODE_PARQUET_PATH = DATA_DIR / "postcode_lookup.parquet"
LAD_LOOKUP_PATH = DATA_DIR / "lad_lookup.json"


def get_domain(url: str) -> str | None:
    if not url:
        return None
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    domain = urlparse(url).netloc.lower()
    if domain.startswith("www."):
        domain = domain[4:]
    return domain


def normalize_postcode(pc: str) -> str:
    return re.sub(r"\s+", "", pc).upper()


async def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Load admin_scraper_lookup.json
    logger.info("Loading admin_scraper_lookup.json")
    with open(SCRAPER_LOOKUP_PATH) as f:
        domain_to_scraper = json.load(f)

    # 2. Fetch input.json and build LAD -> Council mapping
    logger.info("Fetching input.json")
    async with httpx.AsyncClient() as client:
        resp = await client.get(INPUT_JSON_URL)
        resp.raise_for_status()
        input_data = resp.json()

    lad_to_council = {}
    for key, council in input_data.items():
        lad_codes = []
        if "LAD24CD" in council:
            lad_codes.append(council["LAD24CD"])
        if "supported_councils_LAD24CD" in council:
            lad_codes.extend(council["supported_councils_LAD24CD"])

        if not lad_codes:
            continue

        name = council.get("wiki_name") or key
        url = council.get("url")
        domain = get_domain(url)
        scraper_id = domain_to_scraper.get(domain)

        for lad in lad_codes:
            if lad not in lad_to_council or (not lad_to_council[lad]["scraper_id"] and scraper_id):
                lad_to_council[lad] = {
                    "name": name,
                    "scraper_id": scraper_id,
                    "url": url,
                }

    logger.info("Found %d LAD mappings", len(lad_to_council))
    with open(LAD_LOOKUP_PATH, "w") as f:
        json.dump(lad_to_council, f, indent=2)

    # 3. Fetch ONS CSV and convert to Parquet using ibis
    logger.info("Fetching ONS CSV (this may take a while)")
    csv_file = ROOT_DIR / "ons_postcodes.csv"
    if not csv_file.exists():
        async with httpx.AsyncClient(timeout=300, follow_redirects=True) as client:
            async with client.stream("GET", ONS_URL) as response:
                response.raise_for_status()
                with open(csv_file, "wb") as f:
                    async for chunk in response.aiter_bytes():
                        f.write(chunk)
    else:
        logger.info("Using existing ons_postcodes.csv")

    if csv_file.stat().st_size == 0:
        logger.error("CSV file is empty")
        return

    logger.info("Processing CSV with DuckDB via ibis")
    # Use duckdb directly to read only required columns for efficiency
    con = ibis.duckdb.connect()

    # We need to find which column is PCDS and which is LAD CD
    # We'll read the header first
    import csv
    with open(csv_file, 'r', encoding='utf-8-sig') as f:
        reader = csv.reader(f)
        header = next(reader)

    pcds_col = next((c for c in header if c.lower() == "pcds"), None)
    lad_col = next((c for c in header if c.lower().startswith("lad") and c.lower().endswith("cd")), None)

    if not pcds_col or not lad_col:
        logger.error("Could not find required columns in header: %s", header)
        return

    logger.info("Using columns: %s, %s", pcds_col, lad_col)

    # Register the CSV as a table and select only what we need
    # DuckDB's read_csv is very fast and can select columns
    t = con.read_csv(csv_file)

    clean_pc = t[pcds_col].upper().replace(" ", "")

    res = t.select(
        postcode=clean_pc,
        lad_code=t[lad_col]
    ).distinct()

    logger.info("Saving to parquet at %s", POSTCODE_PARQUET_PATH)
    res.to_parquet(POSTCODE_PARQUET_PATH)
    logger.info("Done!")

    # Cleanup CSV to save space if needed
    # csv_file.unlink()


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
