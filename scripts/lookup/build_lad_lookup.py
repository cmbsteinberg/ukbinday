"""Rebuild the LAD mapping from ground truth.

Two stages, deliberately separate:

  build_base()  ONSPD parquet codes + ONS boundary names + GOV.UK Local Links
                Manager URLs        ->  pipeline/data/lad_base.json
  compose()     lad_base.json + pipeline/data/scraper_lad_map.json
                                    ->  api/data/lad_lookup.json

Stage 1 needs the upstream sources in the fetch cache, so it only runs after
`scripts/lookup/fetch_latest.sh` and only when ONS/GOV.UK publish something new.
Its output is committed. Stage 2 reads nothing but committed files, so
`sync_all.py` and CI can rebuild the API's mapping at any time.

The keys of lad_base.json are exactly the LAD codes that
`pipeline/data/onspd_postcode_lad.parquet` can return, because those are the
only codes `/council/{postcode}` will ever look up
(`api/services/council_lookup.py`). Boundary and GOV.UK rows are joined onto
that set, never added to it.

Usage:
    uv run python -m scripts.lookup.build_lad_lookup            # base + compose
    uv run python -m scripts.lookup.build_lad_lookup --compose  # compose only
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import sys
from pathlib import Path

import duckdb

from pipeline.shared import normalise_domain

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent.parent
ONSPD_PARQUET = ROOT / "pipeline" / "data" / "onspd_postcode_lad.parquet"
LAD_BASE_PATH = ROOT / "pipeline" / "data" / "lad_base.json"
SCRAPER_MAP_PATH = ROOT / "pipeline" / "data" / "scraper_lad_map.json"
LAD_LOOKUP_PATH = ROOT / "api" / "data" / "lad_lookup.json"

CACHE_DIR = Path(
    os.environ.get("BINS_DATA_CACHE", Path.home() / ".cache" / "bins-data")
)
BOUNDARY_NAMES_PATH = CACHE_DIR / "lad_names.json"
LOCAL_LINKS_PATH = CACHE_DIR / "local_links_manager.csv"

# GOV.UK Local Links Manager service taxonomy: LGSL 524 is "household waste
# collection", LGIL 8 is "providing information" (i.e. the bin-day page rather
# than a report-a-problem form). Prefer LGIL 8, fall back to any LGSL 524 row.
LGSL_HOUSEHOLD_WASTE = "524"
LGIL_INFORMATION = "8"

# Pseudo-codes ONSPD uses for postcodes outside the UK LAD system. Not councils:
# no boundary, no GOV.UK link, no bin service. Excluded from the mapping so that
# every key in lad_base.json names a real authority.
PSEUDO_CODES = {
    "L99999999",  # Channel Islands
    "M99999999",  # Isle of Man
}

# Upstream sources disagree about which edition of the code list they are on, so
# rows keyed by a superseded code are re-keyed onto the code ONSPD actually
# returns. Each pair was verified by identical authority name in both sources.
#
# ONS boundaries (LAD_MAY_2025) lead ONSPD on the South Yorkshire recodes:
#   boundary E08000038/39 == ONSPD E08000016/19
# GOV.UK Local Links Manager lags ONS on the 2023 reorganisations:
#   E10000023 North Yorkshire (county) -> E06000065 (unitary)
#   S12000015/24/44/46 -> the 2019 Scottish recodes
CODE_ALIASES = {
    "E08000038": "E08000016",  # Barnsley
    "E08000039": "E08000019",  # Sheffield
    "E10000023": "E06000065",  # North Yorkshire
    "S12000015": "S12000047",  # Fife
    "S12000024": "S12000048",  # Perth and Kinross
    "S12000046": "S12000049",  # Glasgow City
    "S12000044": "S12000050",  # North Lanarkshire
}


# One scraper legitimately serves many councils via their public Google
# Calendar feeds, so its domain never matches any council's. Any other
# domain mismatch is a wiring bug worth shouting about.
# NOTE 2026-09-03: the calendar scraper is currently blocklisted (see
# "unwired_lads" in pipeline/lad_overrides.json) — its URL is the shared
# UKBCD *test* fixture, not per-council data. Kept here so the exemption
# still applies if real per-council feeds ever re-wire it.
PASSTHROUGH_SCRAPERS = {"ukbcd_google_public_calendar_council"}

# Domain words that identify a host rather than a council.
_GENERIC_DOMAIN_WORDS = {
    "gov", "uk", "co", "com", "org", "net", "wales", "scot",
    "cloud", "azurewebsites", "www",
}


def _canonical(code: str) -> str:
    return CODE_ALIASES.get(code, code)


def _domain_words(domain: str) -> set[str]:
    return {
        w
        for w in domain.replace("-", ".").split(".")
        if w not in _GENERIC_DOMAIN_WORDS and len(w) > 3
    }


def check_scraper_matches_council(lookup: dict[str, dict]) -> list[str]:
    """Warn where a LAD's scraper looks like it belongs to a different council.

    input.json decides which council a scraper serves, and its `LAD24CD` and
    `url` fields are unvalidated upstream — a wrong one silently serves another
    council's bin days (E06000008 once resolved to Blaby's scraper because
    input.json listed Blackburn with Blaby's URL). `govuk_url` is an independent
    per-LAD domain from GOV.UK, so disagreement between it and the scraper's own
    URL is a cheap signal. Councils that outsource to a third-party portal
    legitimately disagree, so a scraper whose name matches the council name is
    accepted too.
    """
    suspect = []
    for code, entry in sorted(lookup.items(), key=lambda kv: kv[1]["name"]):
        scraper_id, url, govuk_url = (
            entry["scraper_id"],
            entry["url"],
            entry["govuk_url"],
        )
        if not scraper_id or not url or not govuk_url:
            continue
        if scraper_id in PASSTHROUGH_SCRAPERS:
            continue
        scraper_domain = normalise_domain(url)
        if _domain_words(scraper_domain) & _domain_words(normalise_domain(govuk_url)):
            continue
        stem = scraper_id.split("_", 1)[-1]
        name_words = {w.lower() for w in entry["name"].replace(",", " ").split()}
        if any(len(w) > 3 and w[:5] in stem for w in name_words):
            continue
        suspect.append(code)
        logger.warning(
            "  %s %s -> %s (%s) but GOV.UK lists %s",
            code,
            entry["name"],
            scraper_id,
            scraper_domain,
            normalise_domain(govuk_url),
        )
    if suspect:
        logger.warning(
            "%d LAD(s) wired to a scraper whose domain matches neither the "
            "council name nor its GOV.UK page — check for a bad LAD24CD or url "
            "in input.json, and override in pipeline/lad_overrides.json",
            len(suspect),
        )
    return suspect


def onspd_lad_codes() -> list[str]:
    """The distinct LAD codes `/council/{postcode}` can resolve, minus pseudo-codes."""
    con = duckdb.connect()
    try:
        rows = con.execute(
            "SELECT DISTINCT lad_code FROM read_parquet(?) ORDER BY lad_code",
            [str(ONSPD_PARQUET)],
        ).fetchall()
    finally:
        con.close()
    return [r[0] for r in rows if r[0] not in PSEUDO_CODES]


def _load_boundary_names() -> dict[str, str]:
    """LAD code -> canonical ONS name, from the cached boundary attribute query."""
    payload = json.loads(BOUNDARY_NAMES_PATH.read_text())
    names: dict[str, str] = {}
    for feature in payload["features"]:
        attrs = feature["attributes"]
        code = next(v for k, v in attrs.items() if k.endswith("CD"))
        name = next(v for k, v in attrs.items() if k.endswith("NM"))
        names[_canonical(code)] = name
    return names


def _load_govuk_urls() -> dict[str, str]:
    """LAD code -> GOV.UK household-waste page, preferring LGIL 8."""
    preferred: dict[str, str] = {}
    fallback: dict[str, str] = {}
    with open(LOCAL_LINKS_PATH, newline="") as f:
        for row in csv.DictReader(f):
            if row["LGSL"] != LGSL_HOUSEHOLD_WASTE or not row["URL"]:
                continue
            code = _canonical(row["GSS"])
            if row["LGIL"] == LGIL_INFORMATION:
                preferred.setdefault(code, row["URL"])
            else:
                fallback.setdefault(code, row["URL"])
    return {**fallback, **preferred}


def build_base() -> dict[str, dict]:
    """Write lad_base.json: every ONSPD LAD code with its ONS name and GOV.UK URL."""
    missing = [p for p in (BOUNDARY_NAMES_PATH, LOCAL_LINKS_PATH) if not p.exists()]
    if missing:
        raise SystemExit(
            "Missing cached sources:\n  "
            + "\n  ".join(str(p) for p in missing)
            + "\nRun scripts/lookup/fetch_latest.sh first."
        )

    codes = onspd_lad_codes()
    names = _load_boundary_names()
    urls = _load_govuk_urls()

    unnamed = [c for c in codes if c not in names]
    if unnamed:
        # A code ONSPD returns that no source can name means the alias table is
        # stale after a reorganisation. Failing loud beats shipping a null name.
        raise SystemExit(
            f"{len(unnamed)} ONSPD codes have no name in any source: {unnamed}\n"
            "Add the successor/predecessor pair to CODE_ALIASES."
        )

    base = {
        code: {"name": names[code], "govuk_url": urls.get(code)} for code in codes
    }
    base = dict(sorted(base.items(), key=lambda kv: kv[1]["name"]))

    LAD_BASE_PATH.write_text(json.dumps(base, indent=2, ensure_ascii=False) + "\n")
    no_url = [c for c in base if not base[c]["govuk_url"]]
    logger.info(
        "lad_base.json: %d LADs (%d with a GOV.UK waste URL, %d without: %s)",
        len(base),
        len(base) - len(no_url),
        len(no_url),
        ", ".join(no_url) or "-",
    )
    return base


def compose() -> dict[str, dict]:
    """Write api/data/lad_lookup.json from the base plus this sync's scraper wiring."""
    if not LAD_BASE_PATH.exists():
        raise SystemExit(
            f"{LAD_BASE_PATH} not found — run without --compose to build it."
        )
    base = json.loads(LAD_BASE_PATH.read_text())

    if SCRAPER_MAP_PATH.exists():
        scrapers = json.loads(SCRAPER_MAP_PATH.read_text())
    else:
        scrapers = {}
        logger.warning(
            "%s not found — every entry will have a null scraper_id.",
            SCRAPER_MAP_PATH,
        )

    # Deliberately unwired LADs (placeholder scrapers that can never return
    # real data). Stripped here so any sync output re-wiring them is settled
    # back to null at composition time; the reason ships as "status".
    from pipeline.shared import load_deeplink_urls, load_unwired_lads  # noqa: PLC0415

    unwired = load_unwired_lads()
    for code in unwired:
        scrapers.pop(code, None)

    # Unwired LADs whose default deeplink target (GOV.UK) is dead or wrong.
    # A wired scraper's own url always wins, so an override on a wired code is
    # inert — worth saying out loud rather than leaving it to rot.
    deeplink_urls = load_deeplink_urls()
    inert = sorted(code for code in deeplink_urls if scrapers.get(code, {}).get("url"))
    if inert:
        logger.warning(
            "deeplink_urls override(s) ignored — these LADs are wired: %s",
            ", ".join(inert),
        )

    previous = (
        json.loads(LAD_LOOKUP_PATH.read_text()) if LAD_LOOKUP_PATH.exists() else {}
    )

    lookup = {}
    for code, entry in base.items():
        scraper = scrapers.get(code) or {}
        record = {
            "name": entry["name"],
            "scraper_id": scraper.get("scraper_id"),
            "url": scraper.get("url") or deeplink_urls.get(code),
            "govuk_url": entry["govuk_url"],
        }
        if code in unwired:
            record["status"] = unwired[code]
        lookup[code] = record

    stale = sorted(set(scrapers) - set(base))
    if stale:
        logger.info(
            "Dropped %d scraper mapping(s) for codes ONSPD no longer returns: %s",
            len(stale),
            ", ".join(f"{c} ({scrapers[c].get('scraper_id')})" for c in stale),
        )

    added = sorted(set(lookup) - set(previous))
    removed = sorted(set(previous) - set(lookup))
    renamed = [
        (c, previous[c]["name"], lookup[c]["name"])
        for c in sorted(set(lookup) & set(previous))
        if previous[c].get("name") != lookup[c]["name"]
    ]
    logger.info(
        "lad_lookup.json: %d entries (%d with a scraper) — +%d added, -%d removed, "
        "%d renamed",
        len(lookup),
        sum(1 for e in lookup.values() if e["scraper_id"]),
        len(added),
        len(removed),
        len(renamed),
    )
    for code in added:
        logger.info("  + %s %s", code, lookup[code]["name"])
    for code in removed:
        logger.info("  - %s %s", code, previous[code].get("name"))
    for code, was, now in renamed:
        logger.info("  ~ %s %r -> %r", code, was, now)

    check_scraper_matches_council(lookup)

    LAD_LOOKUP_PATH.parent.mkdir(parents=True, exist_ok=True)
    LAD_LOOKUP_PATH.write_text(json.dumps(lookup, indent=2, ensure_ascii=False) + "\n")
    return lookup


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--compose",
        action="store_true",
        help="skip the upstream rebuild; compose lad_lookup.json from committed files",
    )
    args = parser.parse_args()

    if not args.compose:
        build_base()
    compose()
    return 0


if __name__ == "__main__":
    sys.exit(main())
