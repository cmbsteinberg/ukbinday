#!/usr/bin/env python3
"""
Orchestrator for the full scraper sync pipeline.

Flow:
  1. Build council identifiers from UKBCD aliases and the authoritative LAD list
  2. Wipe all scrapers so stale files never linger across syncs
  3. Run HACS sync (clone, patch, copy scrapers)
  4. Filter HACS scrapers against those council identifiers
  5. Run UKBCD sync (fills gaps + writes scraper_lad_map.json)
  5c. Wire retained HACS gaps and preserved scrapers, then compose
      api/data/lad_lookup.json from the LAD ground truth + that map
  6. Regenerate test cases (HACS + UKBCD)
  7. Regenerate postcode lookup (postcode -> LAD code parquet)

input.json supplies scraper aliases; lad_base.json decides which councils exist.
Nothing in this flow may add or drop a council.

Usage:
    uv run python -m pipeline.sync_all
    uv run python -m pipeline.sync_all --include-unmerged
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
from pathlib import Path

import httpx

from pipeline.shared import (
    PIPELINE_DIR,
    PROJECT_ROOT,
    SCRAPER_LAD_MAP_PATH,
    SCRAPERS_DIR,
    extract_gov_uk_prefix,
    extract_url_from_scraper,
    load_lad_overrides,
    load_routing,
    load_unwired_lads,
    normalise_council_name,
    normalise_domain,
)

LAD_LOOKUP_PATH = PROJECT_ROOT / "api" / "data" / "lad_lookup.json"
LAD_BASE_PATH = PIPELINE_DIR / "data" / "lad_base.json"
PORTS_DIR = PIPELINE_DIR / "ports"
PORT_PREFIX = "port_"

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

INPUT_JSON_URL = "https://raw.githubusercontent.com/robbrad/UKBinCollectionData/master/uk_bin_collection/tests/input.json"
NEEDED_COUNCILS_PATH = PIPELINE_DIR / ".needed_councils.json"


def fetch_input_json() -> dict:
    """Fetch input.json from UKBCD GitHub."""
    logger.info("Fetching input.json from UKBCD...")
    resp = httpx.get(INPUT_JSON_URL, timeout=30, follow_redirects=True)
    resp.raise_for_status()
    data = resp.json()
    logger.info("Fetched %d council entries from input.json", len(data))
    return data


def build_needed_identifiers(input_data: dict) -> set[str]:
    """Build a broad set of identifiers for councils listed in input.json.

    Extracts three kinds of identifier per entry so that HACS scrapers can be
    matched even when the input.json URL isn't a *.gov.uk domain:
      1. gov.uk prefix from the URL  (e.g. "sutton")
      2. normalised council name from the key  (e.g. "bristol" from BristolCityCouncil)
      3. primary domain word from non-gov URLs (e.g. "basildon" from mybasildon.powerappsportals.com)
    """
    ids: set[str] = set()
    for key, val in input_data.items():
        if not isinstance(val, dict):
            continue

        # 1. Normalised key (most reliable — always present)
        norm = normalise_council_name(key)
        if norm:
            ids.add(norm)

        url = val.get("url", "")
        if not url:
            continue

        # 2. gov.uk prefix from URL
        prefix = extract_gov_uk_prefix(url)
        if prefix:
            ids.add(prefix)

        # 3. Domain-based heuristic for non-gov URLs (PowerApps, fixmystreet, etc.)
        domain = normalise_domain(url)
        # e.g. "mybasildon.powerappsportals.com" → try "basildon"
        #      "bristolcouncil.powerappsportals.com" → try "bristol"
        first_label = domain.split(".")[0]
        # Strip common prefixes like "my", "online", "waste-services"
        for strip_prefix in ("my", "online", "apps", "forms", "waste", "maps"):
            if first_label.startswith(strip_prefix) and len(first_label) > len(strip_prefix):
                candidate = first_label[len(strip_prefix):].lstrip("-")
                if len(candidate) >= 4:  # avoid spurious short matches
                    ids.add(normalise_council_name(candidate))

    logger.info(
        "Built %d council identifiers from %d input.json entries",
        len(ids),
        sum(1 for v in input_data.values() if isinstance(v, dict)),
    )
    return ids


def build_lad_identifiers(lad_data: dict) -> set[str]:
    """Build HACS matching identifiers from the authoritative council list."""
    ids: set[str] = set()
    for entry in lad_data.values():
        if not isinstance(entry, dict):
            continue
        ids.update(_lad_entry_identifiers(entry))

    logger.info(
        "Built %d council identifiers from %d LAD entries",
        len(ids),
        sum(1 for v in lad_data.values() if isinstance(v, dict)),
    )
    return ids


def _lad_entry_identifiers(entry: dict) -> set[str]:
    identifiers = {normalise_council_name(entry.get("name", ""))}
    govuk_url = entry.get("govuk_url", "")
    if govuk_url:
        identifiers.add(extract_gov_uk_prefix(govuk_url))
    return {identifier for identifier in identifiers if identifier}


def _hacs_scraper_details(path: Path) -> tuple[set[str], str | None]:
    """Return the identifiers and URL used to match one HACS scraper."""
    import ast

    url = extract_url_from_scraper(path)
    identifiers = {
        extract_gov_uk_prefix(url) if url else None,
        normalise_council_name(path.stem.removeprefix("hacs_")),
    }
    try:
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Assign)
                and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id == "TITLE"
                and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)
            ):
                identifiers.add(normalise_council_name(node.value.value))
                break
    except SyntaxError:
        pass
    return {identifier for identifier in identifiers if identifier}, url


def filter_hacs_scrapers(needed_ids: set[str]) -> list[str]:
    """Remove HACS scrapers not recognised by either council catalogue.

    Uses multiple matching strategies:
      1. gov.uk prefix from scraper URL
      2. normalised scraper filename
      3. normalised scraper TITLE

    Returns list of removed scraper names.
    """
    override_hacs = set(load_routing().get("hacs_to_ukbcd", {}).keys())
    preserved = set(load_lad_overrides().get("preserved_scrapers", {}))

    removed = []
    for path in sorted(SCRAPERS_DIR.glob("hacs_*.py")):
        if path.stem in override_hacs or path.stem in preserved:
            continue

        candidates, _ = _hacs_scraper_details(path)
        matched = bool(candidates & needed_ids)

        if not matched:
            path.unlink()
            removed.append(path.stem)
            logger.info(
                "Removed unneeded HACS scraper: %s (no council match; "
                "identifiers=%s)",
                path.stem,
                ",".join(sorted(candidates)),
            )

    return removed


def run_shell(cmd: list[str], description: str) -> None:
    """Run a shell command, streaming output."""
    logger.info("Running: %s", description)
    result = subprocess.run(cmd, cwd=PROJECT_ROOT)
    if result.returncode != 0:
        logger.error("%s failed with exit code %d", description, result.returncode)
        sys.exit(result.returncode)


def save_needed_councils(needed_ids: set[str]) -> None:
    """Save needed council identifiers to a temp file for other scripts to reference."""
    NEEDED_COUNCILS_PATH.write_text(json.dumps(sorted(needed_ids), indent=2))


def _copy_ports() -> list[str]:
    """Copy hand-written scraper ports from pipeline/ports/ into api/scrapers/.

    Each pipeline/ports/<name>.py lands at api/scrapers/port_<name>.py so the
    registry picks them up and they're distinguishable from hacs_/ukbcd_ files.
    Source of truth lives in pipeline/ports/; api/scrapers/ copies are rebuilt
    every sync and must never be edited directly.
    """
    if not PORTS_DIR.is_dir():
        return []
    copied: list[str] = []
    for src in sorted(PORTS_DIR.glob("*.py")):
        if src.name == "__init__.py":
            continue
        dest = SCRAPERS_DIR / src.name
        dest.write_text(src.read_text())
        copied.append(dest.stem)
    return copied


def _wire_lad_hacs_scrapers() -> None:
    """Attach retained HACS scrapers to their authoritative LAD entries.

    HACS has normal priority over UKBCD. Scrapers explicitly routed to UKBCD
    have already been removed, and LAD overrides run after this function.
    Ambiguous matches are skipped so multi-scraper authorities still require
    explicit routing.
    """
    lad_data = json.loads(LAD_BASE_PATH.read_text())
    scraper_map = (
        json.loads(SCRAPER_LAD_MAP_PATH.read_text())
        if SCRAPER_LAD_MAP_PATH.exists()
        else {}
    )
    hacs_scrapers = {}
    for path in sorted(SCRAPERS_DIR.glob("hacs_*.py")):
        identifiers, url = _hacs_scraper_details(path)
        hacs_scrapers[path.stem] = (identifiers, url)

    wired = 0
    for lad, entry in lad_data.items():
        lad_ids = _lad_entry_identifiers(entry)
        matches = [
            (scraper_id, url)
            for scraper_id, (identifiers, url) in hacs_scrapers.items()
            if identifiers & lad_ids
        ]
        if len(matches) == 1:
            scraper_id, url = matches[0]
            if scraper_map.get(lad, {}).get("scraper_id") != scraper_id:
                scraper_map[lad] = {"scraper_id": scraper_id, "url": url}
                wired += 1
        elif len(matches) > 1:
            logger.warning(
                "Multiple HACS scrapers match %s (%s): %s",
                lad,
                entry.get("name"),
                ", ".join(scraper_id for scraper_id, _ in matches),
            )

    if wired:
        SCRAPER_LAD_MAP_PATH.write_text(
            json.dumps(dict(sorted(scraper_map.items())), indent=2) + "\n"
        )
    logger.info("Wired %d LAD entries to retained HACS scrapers", wired)


def _merge_preserved_scrapers() -> None:
    """Wire preserved scrapers and ports into the scraper LAD map.

    Reads the preserved_scrapers and lad_overrides maps from lad_overrides.json
    (scraper_id → [LAD codes]), imports URL from each scraper module, and
    patches the corresponding scraper_lad_map entries. Council names come from
    lad_base.json, not from scraper TITLE constants, so they aren't touched here.
    """
    import importlib

    overrides = load_lad_overrides()
    combined: dict[str, list[str]] = {}
    combined.update(overrides.get("preserved_scrapers", {}))
    combined.update(overrides.get("lad_overrides", {}))
    if not combined:
        return

    scraper_map = (
        json.loads(SCRAPER_LAD_MAP_PATH.read_text())
        if SCRAPER_LAD_MAP_PATH.exists()
        else {}
    )
    patched = 0

    for scraper_id, lad_codes in combined.items():
        try:
            mod = importlib.import_module(f"api.scrapers.{scraper_id}")
            url = getattr(mod, "URL", "")
        except Exception:
            logger.warning("Could not import preserved scraper %s", scraper_id)
            continue

        for lad in lad_codes:
            scraper_map[lad] = {"scraper_id": scraper_id, "url": url}
            patched += 1

    SCRAPER_LAD_MAP_PATH.write_text(
        json.dumps(dict(sorted(scraper_map.items())), indent=2) + "\n"
    )
    logger.info(
        "Merged %d preserved/port scraper entries into scraper_lad_map.json", patched
    )


def _drop_unwired_lads() -> None:
    """Strip blocklisted LADs from scraper_lad_map.json so re-syncs can't
    re-wire placeholders that can never return real data. See
    load_unwired_lads() and the "unwired_lads" map in lad_overrides.json."""
    unwired = load_unwired_lads()
    if not unwired or not SCRAPER_LAD_MAP_PATH.exists():
        return
    scraper_map = json.loads(SCRAPER_LAD_MAP_PATH.read_text())
    dropped = sorted(set(scraper_map) & set(unwired))
    if not dropped:
        return
    for lad in dropped:
        del scraper_map[lad]
    SCRAPER_LAD_MAP_PATH.write_text(
        json.dumps(dict(sorted(scraper_map.items())), indent=2) + "\n"
    )
    logger.info(
        "Dropped %d blocklisted LAD mapping(s): %s",
        len(dropped),
        ", ".join(dropped),
    )


def _check_lad_lookup_consistency() -> None:
    """Warn for any LAD whose scraper_id doesn't exist in api/scrapers/."""
    lad_data = json.loads(LAD_LOOKUP_PATH.read_text())
    missing = []
    for lad, entry in lad_data.items():
        sid = entry.get("scraper_id")
        if sid and not (SCRAPERS_DIR / f"{sid}.py").exists():
            missing.append((lad, sid))
    if missing:
        for lad, sid in missing:
            logger.warning("lad_lookup.json: %s -> %s (file missing)", lad, sid)
        logger.warning("%d LAD entries reference missing scrapers", len(missing))
    else:
        logger.info("lad_lookup.json consistency check passed (%d entries).", len(lad_data))


def main():
    args = sys.argv[1:]
    include_unmerged = "--include-unmerged" in args

    # 1. Build matching identifiers from both scraper aliases and the complete,
    #    authoritative council list. UKBCD coverage must not cap HACS coverage.
    input_data = fetch_input_json()
    lad_data = json.loads(LAD_BASE_PATH.read_text())
    needed_ids = build_needed_identifiers(input_data) | build_lad_identifiers(lad_data)
    save_needed_councils(needed_ids)

    # 2. Wipe all scrapers so stale files never linger across syncs
    #    (preserved scrapers from lad_overrides.json are kept)
    print("\n" + "=" * 50)
    print("=== Cleaning scrapers directory ===")
    print("=" * 50)
    preserved = set(load_lad_overrides().get("preserved_scrapers", {}))
    removed_count = 0
    for path in SCRAPERS_DIR.glob("*.py"):
        if path.name == "__init__.py":
            continue
        if path.stem in preserved:
            continue
        if PORTS_DIR.is_dir() and (PORTS_DIR / path.name).exists():
            # ports are copied fresh from pipeline/ports/ below
            continue
        path.unlink()
        removed_count += 1
    logger.info("Removed %d scraper files (preserved %d).", removed_count, len(preserved))

    # ports are copied after HACS+UKBCD syncs (step 5b) so their files always win

    # 3. Run HACS sync (clone, patch, copy)
    # Clear version file so HACS sync always runs after a full wipe
    hacs_version_file = PIPELINE_DIR / "hacs" / ".upstream_version"
    hacs_version_file.unlink(missing_ok=True)

    print("\n" + "=" * 50)
    print("=== Syncing HACS scrapers ===")
    print("=" * 50)
    run_shell(
        ["bash", str(PIPELINE_DIR / "hacs" / "sync.sh")],
        "HACS sync",
    )

    # 4. Filter HACS scrapers against known councils and scraper aliases
    print("\n" + "=" * 50)
    print("=== Filtering HACS scrapers against council catalogues ===")
    print("=" * 50)
    removed = filter_hacs_scrapers(needed_ids)
    if removed:
        logger.info(
            "Removed %d stale HACS scrapers: %s", len(removed), ", ".join(removed)
        )
    else:
        logger.info("No stale HACS scrapers found.")

    # 5. Run UKBCD sync (fills gaps + builds lad_lookup.json)
    print("\n" + "=" * 50)
    print("=== Syncing UKBCD scrapers (filling gaps) ===")
    print("=" * 50)
    ukbcd_cmd = ["bash", str(PIPELINE_DIR / "ukbcd" / "sync.sh")]
    if include_unmerged:
        ukbcd_cmd.append("--include-unmerged")
    run_shell(ukbcd_cmd, "UKBCD sync")

    # 5b. Copy hand-written ports into api/scrapers/ (source of truth: pipeline/ports/)
    # Done after HACS+UKBCD so their wipes can't clobber port files.
    copied_ports = _copy_ports()
    logger.info("Copied %d ports from pipeline/ports/ into api/scrapers/.", len(copied_ports))

    # 5c. Wire HACS councils absent from UKBCD, apply explicit mappings, then compose
    #     api/data/lad_lookup.json from lad_base.json (ONS/GOV.UK ground truth)
    #     + that map. lad_base.json only changes when upstream does
    #     (scripts/lookup/fetch_latest.sh).
    _wire_lad_hacs_scrapers()
    _merge_preserved_scrapers()
    _drop_unwired_lads()
    run_shell(
        ["uv", "run", "python", "-m", "scripts.lookup.build_lad_lookup", "--compose"],
        "lad_lookup composition",
    )

    # 6. Regenerate test cases (after filtering, so stale scrapers are excluded)
    print("\n" + "=" * 50)
    print("=== Regenerating test cases ===")
    print("=" * 50)
    run_shell(
        ["uv", "run", "python", "-m", "pipeline.hacs.generate_test_lookup"],
        "HACS test cases",
    )
    run_shell(
        ["uv", "run", "python", "-m", "pipeline.ukbcd.generate_test_lookup"],
        "UKBCD test cases",
    )

    # 7. Regenerate postcode lookup (postcode -> LAD code parquet)
    print("\n" + "=" * 50)
    print("=== Regenerating postcode lookup ===")
    print("=" * 50)
    run_shell(
        ["uv", "run", "python", "-m", "scripts.lookup.create_lookup_table"],
        "postcode lookup regeneration",
    )
    # 8. Sanity-check: every scraper_id in lad_lookup.json must exist on disk
    _check_lad_lookup_consistency()

    # Cleanup temp file
    NEEDED_COUNCILS_PATH.unlink(missing_ok=True)

    print("\n" + "=" * 50)
    print("Done. Run 'uv run pytest tests/test_ci.py -v' to verify.")
    print("=" * 50)


if __name__ == "__main__":
    main()
