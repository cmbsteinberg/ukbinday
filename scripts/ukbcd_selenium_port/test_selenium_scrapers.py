#!/usr/bin/env python3
"""
Probe UKBCD Selenium scrapers headlessly to see which still work upstream.

We only care about councils that aren't already covered by a HACS or
non-selenium UKBCD scraper (per api/data/lad_lookup.json). For each of
those, we invoke the upstream collect_data.py CLI in a disposable venv
with a local headless Chrome, capture the JSON output, and validate it
against UKBCD's own output.schema.

Writes scripts/ukbcd_selenium_port/selenium_test_results.json.

Usage:
    uv run python -m scripts.ukbcd_selenium_port.test_selenium_scrapers [--limit N] [--only NAME,...]
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import logging
import os
import re
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from pipeline.shared import LAD_LOOKUP_PATH
from pipeline.ukbcd.patch_scrapers import is_selenium_scraper

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent
PIPELINE_DIR = PROJECT_ROOT / "pipeline"
UPSTREAM_DIR = PIPELINE_DIR / "upstream" / "ukbcd_selenium_clone"
RESULTS_PATH = SCRIPT_DIR / "selenium_test_results.json"

REPO = "robbrad/UKBinCollectionData"
BRANCH = "master"

# Upstream runtime deps needed to import+run a scraper via collect_data.py.
UV_WITH_DEPS = [
    "selenium",
    "webdriver-manager",
    "beautifulsoup4",
    "bs4",
    "lxml",
    "python-dateutil",
    "requests",
    "urllib3",
    "icalendar",
    "jsonschema",
    "holidays",
    "pandas",
    "tabulate",
]

# Per-scraper wall-clock budget. Selenium scrapers can be slow (iframes,
# cookie banners, dropdown waits). 180s is enough for the ones that work
# without being so long a hung Chrome wastes the whole run.
PER_SCRAPER_TIMEOUT_S = 180

# Run a few Chromes concurrently -- more than this and Chrome-on-mac starts
# fighting for the display and chromedriver-manager downloads race.
MAX_PARALLEL = 3


@dataclass
class Result:
    council: str
    lad_codes: list[str]
    url: str
    status: str  # ok | invalid-json | schema-fail | timeout | error
    duration_s: float
    bins_count: int = 0
    error: str = ""
    stdout_tail: str = ""
    stderr_tail: str = ""


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


def clone_upstream() -> Path:
    """Shallow-clone upstream into a stable path so re-runs are cheap."""
    if UPSTREAM_DIR.exists() and (UPSTREAM_DIR / ".git").exists():
        logger.info("Reusing existing upstream clone at %s", UPSTREAM_DIR)
        subprocess.run(
            ["git", "-C", str(UPSTREAM_DIR), "fetch", "--depth", "1", "origin", BRANCH],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "-C", str(UPSTREAM_DIR), "reset", "--hard", f"origin/{BRANCH}"],
            check=True,
            capture_output=True,
        )
        return UPSTREAM_DIR

    UPSTREAM_DIR.parent.mkdir(parents=True, exist_ok=True)
    logger.info("Cloning %s into %s", REPO, UPSTREAM_DIR)
    subprocess.run(
        [
            "git",
            "clone",
            "--depth",
            "1",
            "--branch",
            BRANCH,
            f"https://github.com/{REPO}.git",
            str(UPSTREAM_DIR),
        ],
        check=True,
    )
    return UPSTREAM_DIR


def load_uncovered_selenium(clone_dir: Path) -> list[tuple[str, dict]]:
    """Return (council_name, input_data) for selenium scrapers not covered elsewhere.

    Covered = any LAD code maps to a scraper_id in api/data/lad_lookup.json that
    either starts with 'hacs_' or points to an existing non-selenium 'ukbcd_' file
    (selenium ukbcd files are skipped during sync, so they won't have a file on disk).
    """
    councils_dir = clone_dir / "uk_bin_collection" / "uk_bin_collection" / "councils"
    input_json = clone_dir / "uk_bin_collection" / "tests" / "input.json"
    input_data = json.loads(input_json.read_text())
    lad_lookup = json.loads(LAD_LOOKUP_PATH.read_text())
    scrapers_dir = PROJECT_ROOT / "api" / "scrapers"

    uncovered: list[tuple[str, dict]] = []
    for name, data in input_data.items():
        if not isinstance(data, dict):
            continue
        src = councils_dir / f"{name}.py"
        if not src.exists() or not is_selenium_scraper(src):
            continue

        lads: list[str] = []
        if "LAD24CD" in data:
            lads.append(data["LAD24CD"])
        lads.extend(data.get("supported_councils_LAD24CD", []))

        covered = False
        for lad in lads:
            entry = lad_lookup.get(lad)
            if not entry:
                continue
            sid = entry.get("scraper_id")
            if not sid:
                continue
            # Scraper_id may point to a non-existent file if skipped; require file present.
            if (scrapers_dir / f"{sid}.py").exists():
                covered = True
                break

        if not covered:
            uncovered.append((name, data))

    return uncovered


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------


def build_cli_args(council: str, data: dict) -> list[str]:
    args = [council, data.get("url") or ""]
    if "uprn" in data:
        args.append(f"-u={data['uprn']}")
    if "postcode" in data:
        args.append(f"-p={data['postcode']}")
    if data.get("house_number"):
        args.append(f"-n={data['house_number']}")
    if data.get("skip_get_url"):
        args.append("-s")
    # Always use local chromedriver in headless mode.
    args.append("--headless")
    args.append("--local_browser")
    return args


def _extract_json_blob(stdout: str) -> str:
    """Pull the JSON object out of collect_data.py stdout.

    Logs and prints can interleave with the pretty-printed JSON block, and the
    block itself contains blank lines, so we find the last line that is exactly
    '{' at column 0 and take everything from there until the matching closing
    '}' at column 0.
    """
    lines = stdout.splitlines()
    start = None
    for i, line in enumerate(lines):
        if line == "{":
            start = i
    if start is None:
        return stdout.strip()
    for j in range(len(lines) - 1, start, -1):
        if lines[j] == "}":
            return "\n".join(lines[start : j + 1])
    return "\n".join(lines[start:])


def validate_against_schema(output: str, schema: dict | None = None) -> tuple[bool, str, int]:
    try:
        parsed = json.loads(output)
    except json.JSONDecodeError as e:
        return False, f"json-decode: {e}", 0
    bins = parsed.get("bins") if isinstance(parsed, dict) else None
    if not isinstance(bins, list) or not bins:
        return False, "schema: bins missing or empty", 0
    for b in bins:
        if not isinstance(b, dict) or set(b.keys()) != {"type", "collectionDate"}:
            keys = list(b.keys()) if isinstance(b, dict) else type(b).__name__
            return False, f"schema: bad bin keys {keys}", len(bins)
        if not isinstance(b["type"], str) or not isinstance(b["collectionDate"], str):
            return False, "schema: non-string fields", len(bins)
        if not re.match(r"^\d{2}/\d{2}/\d{4}$", b["collectionDate"]):
            return False, f"schema: bad date {b['collectionDate']!r}", len(bins)
    return True, "", len(bins)


def run_single(council: str, data: dict, clone_dir: Path, schema: dict) -> Result:
    cli = build_cli_args(council, data)
    lads = ([data["LAD24CD"]] if "LAD24CD" in data else []) + data.get("supported_councils_LAD24CD", [])
    url = data.get("url") or ""

    env = os.environ.copy()
    env["PYTHONPATH"] = str(clone_dir) + os.pathsep + str(clone_dir / "uk_bin_collection") + os.pathsep + env.get("PYTHONPATH", "")
    # Keep each run isolated from any interactive Chrome profile.
    with tempfile.TemporaryDirectory(prefix="chrome-profile-") as tmp:
        env["HOME"] = env.get("HOME", tmp)

        cmd = [
            "uv",
            "run",
            "--no-project",
        ]
        for dep in UV_WITH_DEPS:
            cmd.extend(["--with", dep])
        cmd.extend(
            [
                "python",
                "-m",
                "uk_bin_collection.uk_bin_collection.collect_data",
                *cli,
            ]
        )

        logger.info("[%s] starting", council)
        start = time.monotonic()
        try:
            proc = subprocess.run(
                cmd,
                cwd=clone_dir,
                env=env,
                capture_output=True,
                text=True,
                timeout=PER_SCRAPER_TIMEOUT_S,
            )
        except subprocess.TimeoutExpired as e:
            duration = time.monotonic() - start
            return Result(
                council=council,
                lad_codes=lads,
                url=url,
                status="timeout",
                duration_s=duration,
                error=f"timeout after {PER_SCRAPER_TIMEOUT_S}s",
                stdout_tail=(e.stdout or b"").decode(errors="replace")[-800:] if isinstance(e.stdout, bytes) else (e.stdout or "")[-800:],
                stderr_tail=(e.stderr or b"").decode(errors="replace")[-800:] if isinstance(e.stderr, bytes) else (e.stderr or "")[-800:],
            )

        duration = time.monotonic() - start
        stdout = proc.stdout or ""
        stderr = proc.stderr or ""

        if proc.returncode != 0:
            return Result(
                council=council,
                lad_codes=lads,
                url=url,
                status="error",
                duration_s=duration,
                error=f"exit {proc.returncode}",
                stdout_tail=stdout[-800:],
                stderr_tail=stderr[-800:],
            )

        json_text = _extract_json_blob(stdout)

        ok, err, bins = validate_against_schema(json_text, schema)
        if not ok:
            return Result(
                council=council,
                lad_codes=lads,
                url=url,
                status="schema-fail" if err.startswith("schema") else "invalid-json",
                duration_s=duration,
                bins_count=bins,
                error=err,
                stdout_tail=stdout[-800:],
                stderr_tail=stderr[-800:],
            )

        return Result(
            council=council,
            lad_codes=lads,
            url=url,
            status="ok",
            duration_s=duration,
            bins_count=bins,
        )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="Run at most N councils (0 = all).")
    ap.add_argument("--only", type=str, default="", help="Comma-separated council names to run.")
    ap.add_argument("--parallel", type=int, default=MAX_PARALLEL)
    args = ap.parse_args()

    clone_dir = clone_upstream()
    schema = json.loads((clone_dir / "uk_bin_collection" / "tests" / "output.schema").read_text())
    uncovered = load_uncovered_selenium(clone_dir)

    if args.only:
        wanted = {s.strip() for s in args.only.split(",") if s.strip()}
        uncovered = [(n, d) for n, d in uncovered if n in wanted]
    if args.limit:
        uncovered = uncovered[: args.limit]

    logger.info("Testing %d uncovered selenium scrapers", len(uncovered))
    for name, _ in uncovered:
        logger.info("  - %s", name)

    results: list[Result] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.parallel)) as pool:
        futures = {
            pool.submit(run_single, n, d, clone_dir, schema): n for n, d in uncovered
        }
        for fut in concurrent.futures.as_completed(futures):
            name = futures[fut]
            try:
                res = fut.result()
            except Exception as e:
                logger.exception("runner crashed for %s", name)
                res = Result(
                    council=name,
                    lad_codes=[],
                    url="",
                    status="error",
                    duration_s=0,
                    error=f"runner-crash: {type(e).__name__}: {e}",
                )
            logger.info(
                "[%s] %s in %.1fs (bins=%d)%s",
                res.council,
                res.status,
                res.duration_s,
                res.bins_count,
                f" -- {res.error}" if res.error else "",
            )
            results.append(res)

    results.sort(key=lambda r: (r.status != "ok", r.council))
    summary = {
        "total": len(results),
        "ok": sum(1 for r in results if r.status == "ok"),
        "schema_fail": sum(1 for r in results if r.status == "schema-fail"),
        "invalid_json": sum(1 for r in results if r.status == "invalid-json"),
        "timeout": sum(1 for r in results if r.status == "timeout"),
        "error": sum(1 for r in results if r.status == "error"),
    }
    payload = {
        "summary": summary,
        "results": [asdict(r) for r in results],
    }
    RESULTS_PATH.write_text(json.dumps(payload, indent=2))
    logger.info("Wrote %s", RESULTS_PATH)
    logger.info("Summary: %s", summary)

    return 0 if summary["ok"] > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
