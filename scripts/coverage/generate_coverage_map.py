import json
import pathlib
from collections import defaultdict

import duckdb
import httpx

from scripts.lad_status import pass_rate_by_lad

LAD_LOOKUP_PATH = "api/data/lad_lookup.json"
GEOJSON_URL = "https://services1.arcgis.com/ESMARspQHYMw9BZ9/arcgis/rest/services/LAD_MAY_2025_UK_BUC/FeatureServer/0/query?outFields=*&where=1%3D1&f=geojson"
POPULATION_URL = "https://www.ons.gov.uk/file?uri=/peoplepopulationandcommunity/populationandmigration/populationestimates/datasets/populationestimatesforukenglandandwalesscotlandandnorthernireland/mid2024/mye24tablesuk.xlsx"
OUTPUT_DIR = pathlib.Path("api/static")
OUTPUT_GEOJSON = OUTPUT_DIR / "coverage.geojson"

COORD_PRECISION = 5  # ~1m accuracy, significantly reduces file size


def _round_coords(coords):
    """Recursively round coordinates to reduce GeoJSON file size."""
    if isinstance(coords, list) and coords and isinstance(coords[0], (int, float)):
        return [round(c, COORD_PRECISION) for c in coords]
    return [_round_coords(c) for c in coords]


def _coverage_status(council_info: dict) -> str:
    """'working' or 'broken', from the flag scripts.annotate_lad_working
    wrote (rule in scripts/lad_status.py). Untested is not working."""
    if council_info.get("scraper_id") and council_info.get("working"):
        return "working"
    return "broken"


def _load_population_by_lad() -> dict[str, int]:
    """Download ONS mid-year population estimates and return {LAD code: population}."""
    cache_path = pathlib.Path("/tmp/mye24tablesuk.xlsx")
    if not cache_path.exists():
        print("  Downloading ONS population data...")
        resp = httpx.get(POPULATION_URL, timeout=60.0, follow_redirects=True)
        resp.raise_for_status()
        cache_path.write_bytes(resp.content)

    con = duckdb.connect()
    con.execute("INSTALL spatial; LOAD spatial;")
    rows = con.execute(
        "SELECT Field1, Field5 FROM st_read(?, layer='MYE5', "
        "open_options=['HEADERS=DISABLE']) WHERE OGC_FID > 8",
        [str(cache_path)],
    ).fetchall()
    return {code: int(pop) for code, pop in rows if pop is not None}


def main():
    print("Loading LAD lookup...")
    with open(LAD_LOOKUP_PATH) as f:
        lad_lookup = json.load(f)

    print("Loading live test results...")
    pass_rates = pass_rate_by_lad()
    working = sum(1 for info in lad_lookup.values() if info.get("working"))
    no_scraper = sum(1 for info in lad_lookup.values() if not info.get("scraper_id"))
    print(f"  {working} councils working, {len(pass_rates)} with a pass rate from the last run")
    print(f"  {no_scraper} councils have no scraper (not covered)")

    print("Loading population data...")
    population = _load_population_by_lad()
    print(f"  {len(population)} LAD population entries loaded")

    print("Fetching UK boundaries...")
    try:
        response = httpx.get(GEOJSON_URL, timeout=60.0)
        response.raise_for_status()
        geojson_data = response.json()
    except Exception as e:
        print(f"Error fetching GeoJSON: {e}")
        return

    pop_by_status: dict[str, int] = defaultdict(int)

    for feature in geojson_data["features"]:
        lad_cd = feature["properties"].get("LAD25CD", "")
        council_info = lad_lookup.get(lad_cd, {})
        status = _coverage_status(council_info)
        feature["properties"]["coverage_status"] = status
        # Keep backward compat
        feature["properties"]["covered"] = status != "broken"
        if lad_cd in pass_rates:
            feature["properties"]["pass_rate"] = round(pass_rates[lad_cd] * 100)
        lad_pop = population.get(lad_cd, 0)
        if lad_pop:
            feature["properties"]["population"] = lad_pop
        pop_by_status[status] += lad_pop
        feature["geometry"]["coordinates"] = _round_coords(
            feature["geometry"]["coordinates"]
        )

    # Council counts from lad_lookup (our source of truth), not GeoJSON features
    # Multiple LADs can share a module, so count unique modules for "covered"
    total_councils = len(lad_lookup)
    covered_scrapers = {
        info["scraper_id"] for info in lad_lookup.values() if info.get("scraper_id")
    }
    councils_with_scraper = sum(
        1 for info in lad_lookup.values() if info.get("scraper_id")
    )

    # Population from GeoJSON features (aligned with boundary data)
    total_pop = sum(pop_by_status.values())
    covered_pop = pop_by_status["working"]

    if total_pop:
        print("\nPopulation coverage (mid-2024 ONS estimates):")
        print(
            f"  Working:     {pop_by_status['working']:>12,} ({pop_by_status['working'] / total_pop:.1%})"
        )
        print(
            f"  Not covered: {pop_by_status['broken']:>12,} ({pop_by_status['broken'] / total_pop:.1%})"
        )
        print(f"  Total:       {total_pop:>12,}")
        print(f"  Coverage:    {covered_pop / total_pop:.1%} of UK population")

    print(
        f"\nCouncil coverage: {councils_with_scraper} / {total_councils} LADs "
        f"({len(covered_scrapers)} unique scrapers)"
    )

    geojson_data["metadata"] = {
        "councils_covered": councils_with_scraper,
        "councils_total": total_councils,
        "scrapers_unique": len(covered_scrapers),
        "population_covered": covered_pop,
        "population_total": total_pop,
        "population_covered_pct": round(covered_pop / total_pop * 100)
        if total_pop
        else 0,
    }

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Writing {OUTPUT_GEOJSON}...")
    with open(OUTPUT_GEOJSON, "w") as f:
        json.dump(geojson_data, f, separators=(",", ":"))


    print("Done!")


if __name__ == "__main__":
    main()
