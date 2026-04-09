#!/usr/bin/env python3
"""
Orchestrator for the full scraper sync pipeline.

Flow:
  1. Fetch input.json from UKBCD (source of truth for needed councils)
  2. Wipe all scrapers so stale files never linger across syncs
  3. Run HACS sync (clone, patch, copy scrapers)
  4. Filter HACS scrapers: remove any whose gov.uk prefix isn't in input.json
  5. Regenerate admin lookup (so UKBCD sync sees filtered state)
  6. Run UKBCD sync (fills gaps for councils without a HACS scraper)
  7. Final admin lookup regeneration
  8. Regenerate test cases (HACS + UKBCD)
  9. Regenerate LAD lookup (postcode -> council -> scraper)

Usage:
    uv run python -m pipeline.sync_all
    uv run python -m pipeline.sync_all --include-unmerged
"""

from __future__ import annotations

import ast
import json
import logging
import subprocess
import sys
from pathlib import Path

import httpx

from pipeline.shared import (
    PIPELINE_DIR,
    PROJECT_ROOT,
    SCRAPERS_DIR,
    extract_gov_uk_prefix,
    load_overrides,
)

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


def build_needed_prefixes(input_data: dict) -> set[str]:
    """Extract the set of gov.uk prefixes that need scraper coverage."""
    prefixes = set()
    for key, val in input_data.items():
        if not isinstance(val, dict):
            continue
        url = val.get("url", "")
        if not url:
            continue
        prefix = extract_gov_uk_prefix(url)
        if prefix:
            prefixes.add(prefix)
    logger.info("Found %d needed gov.uk prefixes in input.json", len(prefixes))
    return prefixes


def extract_url_from_scraper(path: Path) -> str | None:
    """Parse the URL = '...' constant from a scraper file using AST."""
    try:
        tree = ast.parse(path.read_text())
    except SyntaxError:
        return None
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id == "URL"
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            return node.value.value
    return None


def filter_hacs_scrapers(needed_prefixes: set[str]) -> list[str]:
    """Remove HACS scrapers whose domain isn't needed by input.json.

    Returns list of removed scraper names.
    """
    overrides = load_overrides()
    override_hacs = {
        entry["hacs_scraper"] for entry in overrides.get("hacs_to_ukbcd", {}).values()
    }

    removed = []
    for path in sorted(SCRAPERS_DIR.glob("hacs_*.py")):
        # Only filter HACS scrapers
        # Don't remove scrapers that are explicitly overridden (handled separately)
        if path.stem in override_hacs:
            continue

        url = extract_url_from_scraper(path)
        if not url:
            continue

        prefix = extract_gov_uk_prefix(url)
        if prefix is None:
            # Non-gov.uk scraper -- keep it (rare edge case)
            continue

        # Also try matching by filename (e.g. hacs_solihull_gov_uk -> solihull)
        fname_prefix = None
        stem = path.stem.removeprefix("hacs_")
        if "_gov_uk" in stem:
            fname_prefix = stem.rsplit("_gov_uk", 1)[0].replace("_", "-")

        if prefix not in needed_prefixes and (
            fname_prefix is None or fname_prefix not in needed_prefixes
        ):
            path.unlink()
            removed.append(path.stem)
            logger.info(
                "Removed stale HACS scraper: %s (prefix '%s' not in input.json)",
                path.stem,
                prefix,
            )

    return removed


def run_shell(cmd: list[str], description: str) -> None:
    """Run a shell command, streaming output."""
    logger.info("Running: %s", description)
    result = subprocess.run(cmd, cwd=PROJECT_ROOT)
    if result.returncode != 0:
        logger.error("%s failed with exit code %d", description, result.returncode)
        sys.exit(result.returncode)


def save_needed_councils(needed_prefixes: set[str]) -> None:
    """Save needed councils to a temp file for other scripts to reference."""
    NEEDED_COUNCILS_PATH.write_text(json.dumps(sorted(needed_prefixes), indent=2))


def main():
    args = sys.argv[1:]
    include_unmerged = "--include-unmerged" in args

    # 1. Fetch input.json and build needed set
    input_data = fetch_input_json()
    needed_prefixes = build_needed_prefixes(input_data)
    save_needed_councils(needed_prefixes)

    # 2. Wipe all scrapers so stale files never linger across syncs
    print("\n" + "=" * 50)
    print("=== Cleaning scrapers directory ===")
    print("=" * 50)
    removed_count = 0
    for path in SCRAPERS_DIR.glob("*.py"):
        if path.name == "__init__.py":
            continue
        path.unlink()
        removed_count += 1
    logger.info("Removed %d scraper files.", removed_count)

    # 3. Run HACS sync (clone, patch, copy)
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
    removed = filter_hacs_scrapers(needed_prefixes)
    if removed:
        logger.info(
            "Removed %d stale HACS scrapers: %s", len(removed), ", ".join(removed)
        )
    else:
        logger.info("No stale HACS scrapers found.")

    # 5. Regenerate admin lookup so UKBCD sync sees filtered HACS state
    print("\n" + "=" * 50)
    print("=== Regenerating admin lookup (post-filter) ===")
    print("=" * 50)
    run_shell(
        ["uv", "run", "python", "-m", "scripts.generate_admin_lookup"],
        "admin lookup regeneration (post-filter)",
    )

    # 6. Run UKBCD sync (fills gaps)
    print("\n" + "=" * 50)
    print("=== Syncing UKBCD scrapers (filling gaps) ===")
    print("=" * 50)
    ukbcd_cmd = ["bash", str(PIPELINE_DIR / "ukbcd" / "sync.sh")]
    if include_unmerged:
        ukbcd_cmd.append("--include-unmerged")
    run_shell(ukbcd_cmd, "UKBCD sync")

    # 7. Final admin lookup regeneration (includes UKBCD scrapers)
    print("\n" + "=" * 50)
    print("=== Regenerating admin lookup (final) ===")
    print("=" * 50)
    run_shell(
        ["uv", "run", "python", "-m", "scripts.generate_admin_lookup"],
        "admin lookup regeneration (final)",
    )

    # 8. Regenerate test cases (after filtering, so stale scrapers are excluded)
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

    # 9. Regenerate LAD lookup (postcode -> council -> scraper mapping)
    print("\n" + "=" * 50)
    print("=== Regenerating LAD lookup ===")
    print("=" * 50)
    run_shell(
        ["uv", "run", "python", "-m", "scripts.lookup.create_lookup_table"],
        "LAD lookup regeneration",
    )

    # Cleanup temp file
    NEEDED_COUNCILS_PATH.unlink(missing_ok=True)

    print("\n" + "=" * 50)
    print("Done. Run 'uv run pytest tests/test_ci.py -v' to verify.")
    print("=" * 50)


if __name__ == "__main__":
    main()
