#!/usr/bin/env python3
"""
Check upstream robbrad/UKBinCollectionData branches and open PRs for fixes
to scrapers that are currently failing in our integration tests.

Reads failure data from tests/integration_output.json, queries GitHub for
non-master branches and open PRs, and reports any that touch files matching
our failing robbrad scrapers.

With --include-unmerged, copies fixed scraper files from unmerged branches
into the clone directory so the normal patch pipeline picks them up.
"""

import argparse
import json
import logging
import re
import subprocess
import sys
from pathlib import Path

REPO = "robbrad/UKBinCollectionData"
COUNCILS_PATH = "uk_bin_collection/uk_bin_collection/councils"

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def _get_project_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def _load_failing_ukbcd_scrapers() -> dict[str, str]:
    """Return {scraper_id: error_detail} for failing robbrad scrapers."""
    output_path = _get_project_root() / "tests" / "integration_output.json"
    if not output_path.exists():
        logger.warning("No integration_output.json found — skipping upstream check")
        return {}

    with open(output_path) as f:
        data = json.load(f)

    failures: dict[str, str] = {}
    for _group, info in data.get("failure_groups", {}).items():
        for case in info.get("cases", []):
            council = case.get("council", "")
            if council.startswith("ukbcd_"):
                error = case.get("error_detail", "unknown")
                failures[council] = error
    return failures


def _scraper_id_to_council_class(scraper_id: str) -> str:
    """Convert ukbcd_some_council to SomeCouncil (upstream filename stem)."""
    # Strip ukbcd_ prefix
    name = scraper_id.removeprefix("ukbcd_")
    # Convert snake_case to CamelCase
    return "".join(word.capitalize() for word in name.split("_"))


def _gh_api(endpoint: str, paginate: bool = False) -> list | dict:
    """Call GitHub API via gh CLI."""
    cmd = ["gh", "api", endpoint]
    if paginate:
        cmd.append("--paginate")
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, check=True, timeout=30
        )
        return json.loads(result.stdout)
    except (
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
        json.JSONDecodeError,
    ) as e:
        logger.warning(f"gh api call failed: {e}")
        return []


def _get_non_master_branches() -> list[dict]:
    """Get all branches except master."""
    branches = _gh_api(f"repos/{REPO}/branches", paginate=True)
    if not isinstance(branches, list):
        return []
    return [b for b in branches if b.get("name") != "master"]


def _get_open_prs() -> list[dict]:
    """Get open PRs with their changed files."""
    prs = _gh_api(f"repos/{REPO}/pulls?state=open&per_page=50")
    if not isinstance(prs, list):
        return []
    return prs


def _get_pr_files(pr_number: int) -> list[str]:
    """Get list of changed file paths for a PR."""
    files = _gh_api(f"repos/{REPO}/pulls/{pr_number}/files")
    if not isinstance(files, list):
        return []
    return [f.get("filename", "") for f in files]


def _get_branch_diff_files(branch: str) -> list[str]:
    """Get files changed on a branch vs master."""
    comparison = _gh_api(f"repos/{REPO}/compare/master...{branch}")
    if not isinstance(comparison, dict):
        return []
    return [f.get("filename", "") for f in comparison.get("files", [])]


def _council_file_to_scraper_id(filepath: str) -> str | None:
    """Convert upstream council filepath to our scraper ID.

    Uses the same logic as patch_scrapers.py line 349:
      "ukbcd_" + re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()
    """
    if not filepath.endswith(".py"):
        return None
    stem = Path(filepath).stem
    if stem.startswith("_") or stem == "__init__":
        return None
    return "ukbcd_" + re.sub(r"(?<!^)(?=[A-Z])", "_", stem).lower()


def _fetch_file_from_branch(branch: str, filepath: str) -> str | None:
    """Fetch raw file content from a specific branch."""
    cmd = [
        "gh",
        "api",
        f"repos/{REPO}/contents/{filepath}?ref={branch}",
        "-H",
        "Accept: application/vnd.github.raw+json",
    ]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, check=True, timeout=30
        )
        return result.stdout
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None


def _apply_unmerged_fix(clone_dir: Path, branch: str, filepath: str) -> bool:
    """Download a fixed file from an unmerged branch into the clone directory."""
    content = _fetch_file_from_branch(branch, filepath)
    if content is None:
        return False

    target = clone_dir / filepath
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)
    logger.info(f"  Applied {Path(filepath).name} from branch '{branch}'")
    return True


def check_upstream_fixes(
    clone_dir: Path | None = None,
    include_unmerged: bool = False,
) -> list[dict]:
    """Check for upstream fixes to our failing scrapers.

    Returns list of matches: [{scraper_id, error, source, ref, pr_number?, title?, url?}]
    """
    failures = _load_failing_ukbcd_scrapers()
    if not failures:
        logger.info("No failing robbrad scrapers — nothing to check upstream")
        return []

    logger.info(
        f"Checking upstream for fixes to {len(failures)} failing robbrad scrapers..."
    )

    # Build lookup: upstream council filename stem -> our scraper_id
    scraper_to_class = {}
    for scraper_id in failures:
        class_name = _scraper_id_to_council_class(scraper_id)
        scraper_to_class[scraper_id] = class_name

    matches: list[dict] = []

    # Check open PRs
    prs = _get_open_prs()
    for pr in prs:
        pr_number = pr["number"]
        pr_title = pr.get("title", "")
        pr_branch = pr.get("head", {}).get("ref", "")
        pr_url = pr.get("html_url", "")

        files = _get_pr_files(pr_number)
        council_files = [
            f for f in files if f.startswith(COUNCILS_PATH) and f.endswith(".py")
        ]

        for filepath in council_files:
            scraper_id = _council_file_to_scraper_id(filepath)
            if scraper_id and scraper_id in failures:
                match = {
                    "scraper_id": scraper_id,
                    "error": failures[scraper_id],
                    "source": "open_pr",
                    "ref": pr_branch,
                    "pr_number": pr_number,
                    "title": pr_title,
                    "url": pr_url,
                    "filepath": filepath,
                }
                matches.append(match)

                if include_unmerged and clone_dir:
                    _apply_unmerged_fix(clone_dir, pr_branch, filepath)

    # Check non-master branches (that aren't already covered by PRs)
    pr_branches = {pr.get("head", {}).get("ref", "") for pr in prs}
    branches = _get_non_master_branches()
    for branch_info in branches:
        branch_name = branch_info["name"]
        if branch_name in pr_branches:
            continue  # Already checked via PR

        files = _get_branch_diff_files(branch_name)
        council_files = [
            f for f in files if f.startswith(COUNCILS_PATH) and f.endswith(".py")
        ]

        for filepath in council_files:
            scraper_id = _council_file_to_scraper_id(filepath)
            if scraper_id and scraper_id in failures:
                match = {
                    "scraper_id": scraper_id,
                    "error": failures[scraper_id],
                    "source": "branch",
                    "ref": branch_name,
                    "filepath": filepath,
                }
                matches.append(match)

                if include_unmerged and clone_dir:
                    _apply_unmerged_fix(clone_dir, branch_name, filepath)

    # Report
    if matches:
        logger.info(f"\nFound {len(matches)} upstream fix(es) for failing scrapers:\n")
        for m in matches:
            source_label = (
                f"PR #{m['pr_number']} ({m.get('title', '')})"
                if m["source"] == "open_pr"
                else f"branch '{m['ref']}'"
            )
            action = " [APPLIED]" if include_unmerged and clone_dir else ""
            logger.info(f"  {m['scraper_id']}: {source_label}{action}")
            logger.info(f"    Error: {m['error'][:100]}")
            if m.get("url"):
                logger.info(f"    URL: {m['url']}")
    else:
        logger.info("No upstream fixes found for currently failing scrapers")

    return matches


def main():
    parser = argparse.ArgumentParser(
        description="Check upstream UKBCD for fixes to failing scrapers"
    )
    parser.add_argument(
        "--clone-dir", type=Path, help="Clone directory (for --include-unmerged)"
    )
    parser.add_argument(
        "--include-unmerged",
        action="store_true",
        help="Apply fixes from unmerged branches/PRs into the clone directory",
    )
    args = parser.parse_args()

    if args.include_unmerged and not args.clone_dir:
        parser.error("--include-unmerged requires --clone-dir")

    matches = check_upstream_fixes(
        clone_dir=args.clone_dir,
        include_unmerged=args.include_unmerged,
    )

    # Exit code: 0 if no fixes found, 1 if fixes available (useful for CI)
    sys.exit(1 if matches and not args.include_unmerged else 0)


if __name__ == "__main__":
    main()
