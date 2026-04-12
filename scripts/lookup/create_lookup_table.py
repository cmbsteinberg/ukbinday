import logging
import shutil
from pathlib import Path

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

ROOT_DIR = Path(__file__).parent.parent.parent
DATA_DIR = ROOT_DIR / "api" / "data"
POSTCODE_PARQUET_PATH = DATA_DIR / "postcode_lookup.parquet"
ONSPD_SOURCE = ROOT_DIR / "pipeline" / "onspd_postcode_lad.parquet"


async def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    if not ONSPD_SOURCE.exists():
        logger.error(
            "ONSPD parquet not found at %s. "
            "Download the ONSPD multi_csv zip, unzip, and run: "
            "python -c \"import duckdb; con=duckdb.connect(); con.execute(\\\""  # noqa
            "COPY (SELECT DISTINCT upper(replace(pcds,' ','')) AS postcode, "
            "oslaua AS lad_code FROM read_csv('ONSPD_*/Data/multi_csv/*.csv', "
            "union_by_name=true, all_varchar=true) WHERE oslaua IS NOT NULL "
            "AND oslaua != '') TO 'pipeline/onspd_postcode_lad.parquet' "
            "(FORMAT PARQUET)\\\")\"",
            ONSPD_SOURCE,
        )
        return

    logger.info("Copying ONSPD parquet to %s", POSTCODE_PARQUET_PATH)
    shutil.copy2(ONSPD_SOURCE, POSTCODE_PARQUET_PATH)
    logger.info("Done!")


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
