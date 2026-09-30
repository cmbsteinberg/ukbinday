"""Annotate lad_lookup.json with a 'working' field from the latest live test run.

The rule lives in scripts/lad_status.py. Run this before generate_sankey and
the coverage map; both read the flag it writes.

Usage:
    uv run python -m scripts.annotate_lad_working
"""

import json
from pathlib import Path

from scripts.lad_status import working_by_lad

ROOT = Path(__file__).resolve().parent.parent
LAD_PATH = ROOT / "api" / "data" / "lad_lookup.json"


def annotate():
    with open(LAD_PATH) as f:
        lad = json.load(f)

    working = working_by_lad(lad)
    for code, info in lad.items():
        info["working"] = working[code]

    with open(LAD_PATH, "w") as f:
        json.dump(lad, f, indent=2, ensure_ascii=False)
        f.write("\n")

    total = len(lad)
    n = sum(working.values())
    print(f"Annotated {total} LADs: {n} working, {total - n} not working")


if __name__ == "__main__":
    annotate()
