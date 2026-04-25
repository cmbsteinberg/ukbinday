"""Generate the Mermaid sankey diagram in README.md from lad_lookup.json and integration_output.json."""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LAD_PATH = ROOT / "api" / "data" / "lad_lookup.json"
INTEGRATION_PATH = ROOT / "tests" / "output" / "integration_output.json"
README_PATH = ROOT / "README.md"


def load_data():
    with open(LAD_PATH) as f:
        lad = json.load(f)
    with open(INTEGRATION_PATH) as f:
        integration = json.load(f)
    return lad, integration


def compute_counts(lad, integration):
    # Per-council pass/fail from all_results
    council_results = {}
    for r in integration["all_results"]:
        c = r["council"]
        if c not in council_results:
            council_results[c] = {"pass": 0, "fail": 0}
        if r.get("passed", False):
            council_results[c]["pass"] += 1
        else:
            council_results[c]["fail"] += 1

    # Classify LADs
    hacs_total = 0
    ukbcd_total = 0
    not_supported = 0
    hacs_pass = 0
    hacs_fail = 0
    ukbcd_pass = 0
    ukbcd_fail = 0

    for info in lad.values():
        sid = info.get("scraper_id")
        if sid is None:
            not_supported += 1
            continue

        is_hacs = sid.startswith("hacs_")
        if is_hacs:
            hacs_total += 1
        else:
            ukbcd_total += 1

        # A scraper with any passes counts as passing; no tests also counts as passing
        results = council_results.get(sid)
        passing = results is None or results["pass"] > 0

        if is_hacs:
            if passing:
                hacs_pass += 1
            else:
                hacs_fail += 1
        else:
            if passing:
                ukbcd_pass += 1
            else:
                ukbcd_fail += 1

    return {
        "total": len(lad),
        "hacs_total": hacs_total,
        "ukbcd_total": ukbcd_total,
        "not_supported": not_supported,
        "hacs_pass": hacs_pass,
        "hacs_fail": hacs_fail,
        "ukbcd_pass": ukbcd_pass,
        "ukbcd_fail": ukbcd_fail,
    }


def build_mermaid(c):
    lines = [
        "```mermaid",
        "---",
        "config:",
        "  sankey:",
        "    width: 800",
        "    height: 400",
        "    linkColor: source",
        "    nodeAlignment: left",
        "---",
        "sankey-beta",
        "",
        f'"LAD Codes","HACS",{c["hacs_total"]}',
        f'"LAD Codes","UKBCD",{c["ukbcd_total"]}',
        f'"LAD Codes","Not Supported",{c["not_supported"]}',
        "",
        f'"HACS","Passing",{c["hacs_pass"]}',
        f'"HACS","Failing",{c["hacs_fail"]}',
        "",
        f'"UKBCD","UKBCD Passing",{c["ukbcd_pass"]}',
        f'"UKBCD","UKBCD Failing",{c["ukbcd_fail"]}',
        "```",
    ]
    return "\n".join(lines)


def update_readme(mermaid_block):
    readme = README_PATH.read_text()
    pattern = re.compile(r"```mermaid\n---\nconfig:\n\s+sankey:.*?```", re.DOTALL)
    if pattern.search(readme):
        updated = pattern.sub(mermaid_block, readme)
    else:
        raise ValueError("Could not find existing sankey mermaid block in README.md")
    README_PATH.write_text(updated)


def build_badge(c):
    passing = c["hacs_pass"] + c["ukbcd_pass"]
    total = c["hacs_total"] + c["ukbcd_total"]
    pct = round(100 * passing / total) if total else 0
    color = "brightgreen" if pct >= 90 else "green" if pct >= 75 else "yellow" if pct >= 50 else "red"
    return {
        "schemaVersion": 1,
        "label": "councils passing",
        "message": f"{passing}/{total}",
        "color": color,
    }


BADGE_PATH = ROOT / "badge_coverage.json"


def main():
    lad, integration = load_data()
    counts = compute_counts(lad, integration)
    mermaid = build_mermaid(counts)
    update_readme(mermaid)
    badge = build_badge(counts)
    with open(BADGE_PATH, "w") as f:
        json.dump(badge, f, indent=2)
        f.write("\n")
    print(f"Updated README.md sankey: {counts}")
    print(f"Updated badge: {badge['message']}")


if __name__ == "__main__":
    main()
