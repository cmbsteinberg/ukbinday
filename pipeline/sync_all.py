#!/usr/bin/env python3
"""
Orchestrator for the full scraper sync pipeline.

Flow:
  1. Fetch input.json from UKBCD (source of truth for needed councils)
  2. Wipe all scrapers so stale files never linger across syncs
  3. Run HACS sync (clone, patch, copy scrapers)
  4. Filter HACS scrapers: remove any whose gov.uk prefix isn't in input.json
  5. Run UKBCD sync (fills gaps + builds lad_lookup.json with scraper IDs)
  6. Regenerate test cases (HACS + UKBCD)
  7. Regenerate postcode lookup (postcode -> LAD code parquet)

Usage:
    uv run python -m pipeline.sync_all
    uv run python -m pipeline.sync_all --include-unmerged
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys

import httpx

from pipeline.shared import (
    PIPELINE_DIR,
    PROJECT_ROOT,
    SCRAPERS_DIR,
    extract_gov_uk_prefix,
    extract_url_from_scraper,
    load_overrides,
    normalise_council_name,
    normalise_domain,
)

LAD_LOOKUP_PATH = PROJECT_ROOT / "api" / "data" / "lad_lookup.json"
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


def filter_hacs_scrapers(needed_ids: set[str]) -> list[str]:
    """Remove HACS scrapers whose council isn't needed by input.json.

    Uses multiple matching strategies:
      1. gov.uk prefix from scraper URL
      2. normalised scraper filename
      3. normalised scraper TITLE

    Returns list of removed scraper names.
    """
    import ast

    overrides = load_overrides()
    override_hacs = {
        entry["hacs_scraper"] for entry in overrides.get("hacs_to_ukbcd", {}).values()
    }
    preserved = set(overrides.get("preserved_scrapers", {}))

    removed = []
    for path in sorted(SCRAPERS_DIR.glob("hacs_*.py")):
        if path.stem in override_hacs or path.stem in preserved:
            continue

        # Strategy 1: gov.uk prefix from scraper URL
        url = extract_url_from_scraper(path)
        url_prefix = extract_gov_uk_prefix(url) if url else None

        # Strategy 2: normalised filename (strip hacs_ prefix + domain suffix)
        fname_norm = normalise_council_name(path.stem.removeprefix("hacs_"))

        # Strategy 3: TITLE from scraper source
        title_norm = None
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
                    title_norm = normalise_council_name(node.value.value)
                    break
        except SyntaxError:
            pass

        candidates = [c for c in (url_prefix, fname_norm, title_norm) if c]
        matched = any(c in needed_ids for c in candidates)

        if not matched:
            path.unlink()
            removed.append(path.stem)
            logger.info(
                "Removed unneeded HACS scraper: %s (no match in input.json; "
                "url_prefix=%s, fname=%s, title=%s)",
                path.stem,
                url_prefix,
                fname_norm,
                title_norm,
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


def _merge_preserved_scrapers() -> None:
    """Wire preserved scrapers and ports into lad_lookup.json.

    Reads the preserved_scrapers and ports maps from overrides.json
    (scraper_id → [LAD codes]), imports TITLE and URL from each scraper module,
    and patches the corresponding lad_lookup entries.
    """
    import importlib

    overrides = load_overrides()
    combined: dict[str, list[str]] = {}
    combined.update(overrides.get("preserved_scrapers", {}))
    combined.update(overrides.get("ports", {}))
    if not combined:
        return

    lad_data = json.loads(LAD_LOOKUP_PATH.read_text())
    patched = 0

    for scraper_id, lad_codes in combined.items():
        try:
            mod = importlib.import_module(f"api.scrapers.{scraper_id}")
            title = getattr(mod, "TITLE", scraper_id)
            url = getattr(mod, "URL", "")
        except Exception:
            logger.warning("Could not import preserved scraper %s", scraper_id)
            continue

        for lad in lad_codes:
            if lad in lad_data:
                lad_data[lad]["scraper_id"] = scraper_id
                lad_data[lad]["url"] = url
            else:
                lad_data[lad] = {
                    "name": title,
                    "scraper_id": scraper_id,
                    "url": url,
                }
            patched += 1

    LAD_LOOKUP_PATH.write_text(json.dumps(lad_data, indent=2))
    logger.info("Merged %d preserved/port scraper entries into lad_lookup.json", patched)


def main():
    args = sys.argv[1:]
    include_unmerged = "--include-unmerged" in args

    # 1. Fetch input.json and build needed set
    input_data = fetch_input_json()
    needed_ids = build_needed_identifiers(input_data)
    save_needed_councils(needed_ids)

    # 2. Wipe all scrapers so stale files never linger across syncs
    #    (preserved scrapers from overrides.json are kept)
    print("\n" + "=" * 50)
    print("=== Cleaning scrapers directory ===")
    print("=" * 50)
    overrides = load_overrides()
    preserved = set(overrides.get("preserved_scrapers", {}))
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

    # 4. Filter HACS scrapers against input.json
    print("\n" + "=" * 50)
    print("=== Filtering HACS scrapers against input.json ===")
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

    # 5b. Wire preserved scrapers into lad_lookup.json
    _merge_preserved_scrapers()

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

    # Cleanup temp file
    NEEDED_COUNCILS_PATH.unlink(missing_ok=True)

    print("\n" + "=" * 50)
    print("Done. Run 'uv run pytest tests/test_ci.py -v' to verify.")
    print("=" * 50)


if __name__ == "__main__":
    main()
