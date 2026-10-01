"""Generate the coverage section of README.md (sankey plus the councils without
dates, with reasons) and badge_coverage.json from lad_lookup.json.

Every council a postcode resolves to lands in one of three outcomes:

- dates: its scraper passed the last live run (`working`, written by
  scripts.annotate_lad_working; run that first).
- deeplink: deliberately sent to the council's own page, because no scraper is
  possible. Either unwired (the reason is the `status` note from
  pipeline/lad_overrides.json) or a module with `needs_browser` (captcha, login).
- broken: has a scraper that isn't passing; users get the fallback deeplink
  until it's fixed. The reason is the LAD's status in the last live run.
"""

import json
import re
from pathlib import Path

from api.councils._base import discovery

ROOT = Path(__file__).resolve().parent.parent
LAD_PATH = ROOT / "api" / "data" / "lad_lookup.json"
RESULTS_PATH = ROOT / "tests" / "output" / "lad_integration_output.json"
README_PATH = ROOT / "README.md"
BADGE_PATH = ROOT / "badge_coverage.json"

START, END = "<!-- coverage:start -->", "<!-- coverage:end -->"


def classify(lad: dict, results: dict) -> dict[str, list[tuple[str, str, str]]]:
    """Outcome -> [(LAD code, council name, reason)]; dates rows have no reason."""
    scrapers = {name: discovery.load(name) for name in discovery.module_names()}
    module_for = {code: scrapers[name] for code, name in discovery.by_lad(scrapers).items()}
    out: dict[str, list[tuple[str, str, str]]] = {"dates": [], "deeplink": [], "broken": []}
    for code, info in sorted(lad.items(), key=lambda kv: kv[1]["name"]):
        name = info["name"]
        module = module_for.get(code)
        if module is None and not info.get("scraper_id"):
            reason = (info.get("status") or "no scraper").removeprefix("deeplink-unwired: ")
            out["deeplink"].append((code, name, reason))
        elif module is not None and module.needs_browser:
            out["deeplink"].append((code, name, module.needs_browser))
        elif info.get("working"):
            out["dates"].append((code, name, ""))
        else:
            last = results.get(code, {})
            reason = " / ".join(filter(None, (last.get("status"), last.get("reason")))) or "not in the last live run"
            out["broken"].append((code, name, reason))
    return out


def build_section(groups: dict[str, list[tuple[str, str, str]]]) -> str:
    total = sum(len(rows) for rows in groups.values())
    dates, deeplink, broken = (len(groups[k]) for k in ("dates", "deeplink", "broken"))
    lines = [
        START,
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
        f'"Councils","Bin dates",{dates}',
        f'"Councils","Deeplink (no scraper possible)",{deeplink}',
        f'"Councils","Broken (being fixed)",{broken}',
        "```",
        "",
        f"Of {total} councils, {dates} return bin dates. The other {deeplink + broken} send users to the council's own bin-day page:",
        "",
        f"**Deeplinked by design ({deeplink})**: the council's lookup can't be scraped.",
        "",
        "| Council | Why |",
        "|---|---|",
        *(f"| {name} | {reason} |" for _, name, reason in groups["deeplink"]),
        "",
        f"**Broken ({broken})**: a scraper exists but failed the last live run, usually because the council's site is down.",
        "",
        "| Council | Last run |",
        "|---|---|",
        *(f"| {name} | {reason} |" for _, name, reason in groups["broken"]),
        END,
    ]
    return "\n".join(lines)


def update_readme(section: str) -> None:
    readme = README_PATH.read_text()
    pattern = re.compile(re.escape(START) + r".*?" + re.escape(END), re.DOTALL)
    if not pattern.search(readme):
        raise ValueError(f"Could not find the {START} ... {END} block in README.md")
    README_PATH.write_text(pattern.sub(lambda _: section, readme))


def build_badge(groups: dict[str, list[tuple[str, str, str]]]) -> dict:
    dates = len(groups["dates"])
    total = sum(len(rows) for rows in groups.values())
    pct = round(100 * dates / total) if total else 0
    color = "brightgreen" if pct >= 90 else "green" if pct >= 75 else "yellow" if pct >= 50 else "red"
    return {"schemaVersion": 1, "label": "councils with bin dates", "message": f"{dates}/{total}", "color": color}


def main() -> None:
    lad = json.loads(LAD_PATH.read_text())
    results = json.loads(RESULTS_PATH.read_text()).get("lads", {}) if RESULTS_PATH.exists() else {}
    groups = classify(lad, results)
    update_readme(build_section(groups))
    badge = build_badge(groups)
    BADGE_PATH.write_text(json.dumps(badge, indent=2) + "\n")
    print(f"Updated README.md coverage: { {k: len(v) for k, v in groups.items()} }")
    print(f"Updated badge: {badge['message']}")


if __name__ == "__main__":
    main()
