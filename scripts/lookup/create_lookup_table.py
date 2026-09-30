"""Build the postcode → LAD parquet the API queries, and its ONSUD companion.

Default run publishes the committed pipeline parquet to api/data/, which is all
a normal sync needs:

    uv run python -m scripts.lookup.create_lookup_table

The --from-onspd / --from-onsud modes rebuild the pipeline parquets from an
unpacked ONS release and are driven by scripts/lookup/fetch_latest.sh, which
only invokes them when ONS publishes a new edition. Both stamp the ONS edition
into the parquet's key-value metadata, so a committed artifact can always say
where it came from:

    SELECT * FROM parquet_kv_metadata('pipeline/data/onspd_postcode_lad.parquet');
"""

import argparse
import logging
import shutil
from datetime import UTC, datetime
from pathlib import Path

import duckdb

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

ROOT_DIR = Path(__file__).parent.parent.parent
DATA_DIR = ROOT_DIR / "api" / "data"
POSTCODE_PARQUET_PATH = DATA_DIR / "postcode_lookup.parquet"
PIPELINE_DATA = ROOT_DIR / "pipeline" / "data"
ONSPD_SOURCE = PIPELINE_DATA / "onspd_postcode_lad.parquet"
ONSUD_SOURCE = PIPELINE_DATA / "onsud_uprn_postcode.parquet"

EDITION_KEY = "onspd_edition"

_MISSING_SOURCE_HINT = (
    "ONSPD parquet not found at %s. Run scripts/lookup/fetch_latest.sh to "
    "download the current ONS release and rebuild it."
)


def _copy_with_metadata(
    select_sql: str, source_glob: str, dest: Path, edition: str
) -> None:
    """Run a COPY into `dest`, stamping the ONS edition into parquet metadata."""
    con = duckdb.connect()
    try:
        con.execute(
            f"COPY ({select_sql}) TO ? (FORMAT PARQUET, KV_METADATA {{"
            f"{EDITION_KEY}: ?, source: ?, generated_at: ?}})",
            [
                str(dest),
                edition,
                source_glob,
                datetime.now(UTC).isoformat(timespec="seconds"),
            ],
        )
        rows = con.execute("SELECT count(*) FROM read_parquet(?)", [str(dest)]).fetchone()
    finally:
        con.close()
    logger.info("Wrote %s (%s rows, edition %s)", dest, rows[0], edition)


def build_onspd_parquet(source_dir: Path, edition: str) -> None:
    """postcode → LAD code, from an unpacked ONSPD release's per-area CSVs.

    Postcodes are stored space-stripped and uppercased to match
    `api/services/council_lookup._normalize_postcode`.
    """
    glob = str(source_dir / "Data" / "multi_csv" / "*.csv")
    _copy_with_metadata(
        "SELECT DISTINCT upper(replace(pcds, ' ', '')) AS postcode, "
        "oslaua AS lad_code "
        f"FROM read_csv('{glob}', union_by_name=true, all_varchar=true) "
        "WHERE oslaua IS NOT NULL AND oslaua != ''",
        glob,
        ONSPD_SOURCE,
        edition,
    )


def build_onsud_parquet(source_dir: Path, edition: str) -> None:
    """UPRN → postcode, from an unpacked ONSUD release's per-region CSVs."""
    glob = str(source_dir / "Data" / "ONSUD_*.csv")
    _copy_with_metadata(
        "SELECT DISTINCT try_cast(UPRN AS BIGINT) AS uprn, PCDS AS postcode "
        f"FROM read_csv('{glob}', union_by_name=true, all_varchar=true) "
        "WHERE PCDS IS NOT NULL AND PCDS != ''",
        glob,
        ONSUD_SOURCE,
        edition,
    )


def stamp_edition(parquet: Path, edition: str) -> None:
    """Rewrite an existing parquet in place, adding/replacing the edition stamp.

    Used to label artifacts that predate this metadata, without re-downloading
    the multi-hundred-MB ONS release they came from.
    """
    tmp = parquet.with_suffix(".stamping.parquet")
    _copy_with_metadata(
        f"SELECT * FROM read_parquet('{parquet}')", str(parquet), tmp, edition
    )
    tmp.replace(parquet)
    logger.info("Stamped %s as edition %s", parquet, edition)


def publish() -> int:
    """Copy the committed pipeline ONSPD parquet to where the API reads it."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not ONSPD_SOURCE.exists():
        logger.error(_MISSING_SOURCE_HINT, ONSPD_SOURCE)
        return 1
    logger.info("Copying ONSPD parquet to %s", POSTCODE_PARQUET_PATH)
    # copy2 preserves the parquet's edition metadata along with the bytes.
    shutil.copy2(ONSPD_SOURCE, POSTCODE_PARQUET_PATH)
    logger.info("Done!")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--from-onspd", type=Path, help="unpacked ONSPD release directory"
    )
    parser.add_argument(
        "--from-onsud", type=Path, help="unpacked ONSUD release directory"
    )
    parser.add_argument(
        "--stamp-edition",
        type=Path,
        help="add the --edition stamp to an existing parquet, in place",
    )
    parser.add_argument(
        "--edition",
        help="ONS edition label, e.g. ONSPD_AUG_2026 (required when rebuilding)",
    )
    args = parser.parse_args()

    rebuilding = args.from_onspd or args.from_onsud or args.stamp_edition
    if rebuilding and not args.edition:
        parser.error("--edition is required when rebuilding or stamping a parquet")

    if args.from_onspd:
        build_onspd_parquet(args.from_onspd, args.edition)
    if args.from_onsud:
        build_onsud_parquet(args.from_onsud, args.edition)
    if args.stamp_edition:
        stamp_edition(args.stamp_edition, args.edition)

    if args.from_onsud and not (args.from_onspd or args.stamp_edition):
        # ONSUD alone doesn't change what the API serves.
        return 0
    return publish()


if __name__ == "__main__":
    raise SystemExit(main())
