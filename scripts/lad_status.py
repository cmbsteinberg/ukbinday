"""The one definition of whether a council works, shared by every consumer.

annotate_lad_working writes `working` into api/data/lad_lookup.json from
this; generate_sankey, the badge and the coverage map read that flag back
instead of re-deriving it from raw results with their own rules.

Source preference:
  1. tests/output/lad_integration_output.json (test_lad_integration.py):
     per-LAD status already computed. `unverified` LADs keep their previous
     flag, so a run from a machine that can't reach some councils doesn't
     unmark them.
  2. tests/output/integration_output.json (legacy test_integration.py):
     per-scraper, working if any case passed. A wired scraper with no rows
     is *not* working (it used to count as passing in the sankey/coverage
     map and failing in annotate).
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LAD_OUTPUT_PATH = ROOT / "tests" / "output" / "lad_integration_output.json"
LEGACY_OUTPUT_PATH = ROOT / "tests" / "output" / "integration_output.json"


def working_by_lad(lad_lookup: dict, previous: dict[str, bool] | None = None) -> dict[str, bool]:
    """LAD code -> working, for every LAD in lad_lookup."""
    previous = previous or {code: bool(info.get("working")) for code, info in lad_lookup.items()}
    if LAD_OUTPUT_PATH.exists():
        lads = json.loads(LAD_OUTPUT_PATH.read_text()).get("lads", {})
        out = {}
        for code, info in lad_lookup.items():
            if not info.get("scraper_id"):
                out[code] = False
                continue
            r = lads.get(code)
            # Wired to a different scraper than the one tested: result is stale
            if r is None or r.get("scraper_id") != info["scraper_id"] or r["status"] == "unverified":
                out[code] = previous.get(code, False)
            else:
                out[code] = r["status"] == "working"
        return out

    if not LEGACY_OUTPUT_PATH.exists():
        return previous
    passed: dict[str, bool] = {}
    for r in json.loads(LEGACY_OUTPUT_PATH.read_text()).get("all_results", []):
        passed[r["council"]] = passed.get(r["council"], False) or bool(r["passed"])
    return {
        code: bool(info.get("scraper_id")) and passed.get(info["scraper_id"], False)
        for code, info in lad_lookup.items()
    }
