"""Build the postcode → LAD lookup the API reads, and its ONSUD companion.

Default run shards the committed pipeline parquet into api/data/postcodes/
(one JSON file per outward code), which is all a normal sync needs:

    uv run python -m scripts.lookup.create_lookup_table
    uv run python -m scripts.lookup.create_lookup_table --check  # pre-commit/CI

The --from-onspd / --from-onsud modes rebuild the pipeline parquets from an
unpacked ONS release and are driven by scripts/lookup/fetch_latest.sh, which
only invokes them when ONS publishes a new edition. Both stamp the ONS edition
into the parquet's key-value metadata, so a committed artifact can always say
where it came from:

    SELECT * FROM parquet_kv_metadata('pipeline/data/onspd_postcode_lad.parquet');
"""

import argparse
import json
import logging
import shutil
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

import duckdb

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

ROOT_DIR = Path(__file__).parent.parent.parent
DATA_DIR = ROOT_DIR / "api" / "data"
POSTCODES_DIR = DATA_DIR / "postcodes"
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


def build_shards(source: Path) -> dict[str, bytes]:
    """One JSON file per outward code: `{"lads": [...], "pc": {inward: index}}`.

    Every postcode is listed, even where the outward code is one council, so a
    made-up inward code is still not found. The inward code is always the last
    three characters of a normalised postcode, so the file and key come straight
    from the postcode (see `CouncilLookup`). Output is deterministic, so
    `--check` can compare it byte for byte with what's committed.
    """
    con = duckdb.connect()
    try:
        rows = con.execute(
            "SELECT postcode, lad_code FROM read_parquet(?)", [str(source)]
        ).fetchall()
    finally:
        con.close()

    by_outward: dict[str, dict[str, str]] = defaultdict(dict)
    for postcode, lad in rows:
        by_outward[postcode[:-3]][postcode[-3:]] = lad

    shards = {}
    for outward, inward_to_lad in sorted(by_outward.items()):
        lads = sorted(set(inward_to_lad.values()))
        index = {lad: i for i, lad in enumerate(lads)}
        shard = {
            "lads": lads,
            "pc": {k: index[v] for k, v in sorted(inward_to_lad.items())},
        }
        shards[f"{outward}.json"] = json.dumps(shard, separators=(",", ":")).encode()
    return shards


def write_shards(shards: dict[str, bytes], dest: Path) -> None:
    """Replace `dest` with exactly `shards`, via a sibling temp dir."""
    tmp = dest.with_name(dest.name + ".tmp")
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    for name, data in shards.items():
        (tmp / name).write_bytes(data)
    shutil.rmtree(dest, ignore_errors=True)
    tmp.replace(dest)
    logger.info("Wrote %d shards to %s", len(shards), dest)


def stale_shards(shards: dict[str, bytes], dest: Path) -> list[str]:
    """Names of shards that are missing, extra or different in `dest`."""
    on_disk = {p.name for p in dest.glob("*.json")} if dest.is_dir() else set()
    return sorted(
        name
        for name in on_disk | shards.keys()
        if name not in shards
        or name not in on_disk
        or (dest / name).read_bytes() != shards[name]
    )


def publish(check: bool = False) -> int:
    """Shard the committed pipeline ONSPD parquet into where the API reads it.

    With `check`, write nothing and fail if the committed shards are out of date.
    """
    if not ONSPD_SOURCE.exists():
        logger.error(_MISSING_SOURCE_HINT, ONSPD_SOURCE)
        return 1
    shards = build_shards(ONSPD_SOURCE)
    if not check:
        write_shards(shards, POSTCODES_DIR)
        return 0
    stale = stale_shards(shards, POSTCODES_DIR)
    if stale:
        logger.error(
            "%d postcode shards are out of date with %s (e.g. %s). Run: "
            "uv run python -m scripts.lookup.create_lookup_table",
            len(stale),
            ONSPD_SOURCE.relative_to(ROOT_DIR),
            ", ".join(stale[:5]),
        )
        return 1
    logger.info("%d postcode shards match %s", len(shards), ONSPD_SOURCE.name)
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
    parser.add_argument(
        "--check",
        action="store_true",
        help="write nothing; exit 1 if api/data/postcodes/ is out of date",
    )
    args = parser.parse_args()

    if args.check:
        return publish(check=True)

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
