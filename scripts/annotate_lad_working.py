"""Annotate lad_lookup.json with a 'working' field based on integration test results.

Usage:
    uv run python -m scripts.annotate_lad_working
"""

import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LAD_PATH = ROOT / "api" / "data" / "lad_lookup.json"
INTEGRATION_PATH = ROOT / "tests" / "output" / "integration_output.json"


def load_scraper_pass_counts(integration_path: Path) -> dict[str, dict[str, int]]:
    with open(integration_path) as f:
        data = json.load(f)

    counts: dict[str, dict[str, int]] = defaultdict(lambda: {"passed": 0, "total": 0})
    for r in data.get("all_results", []):
        council = r["council"]
        counts[council]["total"] += 1
        if r["passed"]:
            counts[council]["passed"] += 1

    return dict(counts)


def annotate():
    with open(LAD_PATH) as f:
        lad = json.load(f)

    if not INTEGRATION_PATH.exists():
        print(f"{INTEGRATION_PATH} not found — run integration tests first")
        return

    counts = load_scraper_pass_counts(INTEGRATION_PATH)

    working_count = 0
    for info in lad.values():
        scraper_id = info.get("scraper_id")
        if not scraper_id:
            info["working"] = False
            continue

        results = counts.get(scraper_id)
        info["working"] = results is not None and results["passed"] > 0
        if info["working"]:
            working_count += 1

    with open(LAD_PATH, "w") as f:
        json.dump(lad, f, indent=2, ensure_ascii=False)
        f.write("\n")

    total = len(lad)
    print(f"Annotated {total} LADs: {working_count} working, {total - working_count} not working")


if __name__ == "__main__":
    annotate()
