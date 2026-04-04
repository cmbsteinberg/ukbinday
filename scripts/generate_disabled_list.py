"""
Generate api/data/disabled_scrapers.json from integration test results.

Scrapers with a 0% pass rate (and no UKBCD override) are disabled so users
get a clear "not supported" message instead of a broken response.

To recheck disabled scrapers:
  1. Delete api/data/disabled_scrapers.json
  2. Run integration tests: uv run pytest tests/test_integration.py -v
  3. Regenerate: uv run python -m scripts.generate_disabled_list

Usage:
    uv run python -m scripts.generate_disabled_list
"""

import json
import sys
from collections import defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
INTEGRATION_OUTPUT = PROJECT_ROOT / "tests" / "integration_output.json"
OVERRIDES_PATH = PROJECT_ROOT / "pipeline" / "overrides.json"
OUTPUT_PATH = PROJECT_ROOT / "api" / "data" / "disabled_scrapers.json"


def main():
    if not INTEGRATION_OUTPUT.exists():
        print(f"Error: {INTEGRATION_OUTPUT} not found. Run integration tests first.")
        return 1

    data = json.loads(INTEGRATION_OUTPUT.read_text())
    results = data.get("all_results", [])
    if not results:
        print("No test results found.")
        return 1

    # Compute per-scraper pass rates
    counts: dict[str, dict[str, int]] = defaultdict(lambda: {"passed": 0, "total": 0})
    for r in results:
        council = r["council"]
        counts[council]["total"] += 1
        if r["passed"]:
            counts[council]["passed"] += 1

    broken = {k for k, v in counts.items() if v["passed"] == 0}

    # Exclude scrapers that have UKBCD overrides (those are handled by sync.sh)
    overridden = set()
    if OVERRIDES_PATH.exists():
        overrides = json.loads(OVERRIDES_PATH.read_text())
        for entry in overrides.get("hacs_to_ukbcd", {}).values():
            overridden.add(entry["hacs_scraper"])

    disabled = sorted(broken - overridden)

    output = {
        "disabled": disabled,
        "reason": "0% integration test pass rate",
        "recheck": "Delete this file, run integration tests, then regenerate with: "
        "uv run python -m scripts.generate_disabled_list",
    }

    OUTPUT_PATH.write_text(json.dumps(output, indent=2) + "\n")

    print(f"Disabled {len(disabled)} scrapers (0% pass rate, no override)")
    for s in disabled:
        total = counts[s]["total"]
        print(f"  {s} ({total} test{'s' if total != 1 else ''}, all failed)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
