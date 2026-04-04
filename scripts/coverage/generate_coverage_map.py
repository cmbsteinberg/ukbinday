import json
import pathlib
from collections import defaultdict

import httpx

LAD_LOOKUP_PATH = "api/data/lad_lookup.json"
INTEGRATION_OUTPUT_PATH = "tests/integration_output.json"
GEOJSON_URL = "https://services1.arcgis.com/ESMARspQHYMw9BZ9/arcgis/rest/services/LAD_MAY_2025_UK_BUC/FeatureServer/0/query?outFields=*&where=1%3D1&f=geojson"
OUTPUT_DIR = pathlib.Path("api/static")
OUTPUT_GEOJSON = OUTPUT_DIR / "coverage.geojson"
OUTPUT_MAP_HTML = OUTPUT_DIR / "coverage_map.html"

COORD_PRECISION = 5  # ~1m accuracy, significantly reduces file size


def _round_coords(coords):
    """Recursively round coordinates to reduce GeoJSON file size."""
    if isinstance(coords, list) and coords and isinstance(coords[0], (int, float)):
        return [round(c, COORD_PRECISION) for c in coords]
    return [_round_coords(c) for c in coords]


def _load_scraper_pass_rates() -> dict[str, float]:
    """Compute per-scraper pass rate from integration test output."""
    path = pathlib.Path(INTEGRATION_OUTPUT_PATH)
    if not path.exists():
        print(f"  {INTEGRATION_OUTPUT_PATH} not found, using binary coverage only")
        return {}

    with open(path) as f:
        data = json.load(f)

    results = data.get("all_results", [])
    if not results:
        return {}

    counts: dict[str, dict[str, int]] = defaultdict(lambda: {"passed": 0, "total": 0})
    for r in results:
        council = r["council"]
        counts[council]["total"] += 1
        if r["passed"]:
            counts[council]["passed"] += 1

    return {
        council: c["passed"] / c["total"]
        for council, c in counts.items()
        if c["total"] > 0
    }


def _coverage_status(scraper_id: str | None, pass_rates: dict[str, float]) -> str:
    """Return coverage status: 'working', 'partial', or 'broken'."""
    if not scraper_id:
        return "broken"
    if scraper_id not in pass_rates:
        # Has a scraper but no test results — treat as partial (unverified)
        return "partial"
    rate = pass_rates[scraper_id]
    if rate >= 0.8:
        return "working"
    if rate > 0:
        return "partial"
    return "broken"


def main():
    print("Loading LAD lookup...")
    with open(LAD_LOOKUP_PATH) as f:
        lad_lookup = json.load(f)

    print("Loading integration test results...")
    pass_rates = _load_scraper_pass_rates()
    if pass_rates:
        working = sum(1 for r in pass_rates.values() if r >= 0.8)
        partial = sum(1 for r in pass_rates.values() if 0 < r < 0.8)
        broken = sum(1 for r in pass_rates.values() if r == 0)
        print(
            f"  {len(pass_rates)} scrapers tested: {working} working, {partial} partial, {broken} broken"
        )

    print("Fetching UK boundaries...")
    try:
        response = httpx.get(GEOJSON_URL, timeout=60.0)
        response.raise_for_status()
        geojson_data = response.json()
    except Exception as e:
        print(f"Error fetching GeoJSON: {e}")
        return

    for feature in geojson_data["features"]:
        lad_cd = feature["properties"].get("LAD25CD", "")
        council_info = lad_lookup.get(lad_cd, {})
        scraper_id = council_info.get("scraper_id")
        status = _coverage_status(scraper_id, pass_rates)
        feature["properties"]["coverage_status"] = status
        # Keep backward compat
        feature["properties"]["covered"] = status != "broken"
        if scraper_id and scraper_id in pass_rates:
            feature["properties"]["pass_rate"] = round(pass_rates[scraper_id] * 100)
        feature["geometry"]["coordinates"] = _round_coords(
            feature["geometry"]["coordinates"]
        )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Writing {OUTPUT_GEOJSON}...")
    with open(OUTPUT_GEOJSON, "w") as f:
        json.dump(geojson_data, f, separators=(",", ":"))

    map_html = """\
<!DOCTYPE html>
<html>
<head>
    <title>Coverage Map</title>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
    <style>
        body { margin: 0; padding: 0; }
        #map { height: 600px; width: 100%; }
        .info { padding: 6px 8px; font: 14px/16px Arial, Helvetica, sans-serif; background: white; background: rgba(255,255,255,0.8); box-shadow: 0 0 15px rgba(0,0,0,0.2); border-radius: 5px; }
        .legend { line-height: 18px; color: #555; background: white; padding: 10px; border-radius: 5px; box-shadow: 0 0 15px rgba(0,0,0,0.2); }
        .legend i { width: 18px; height: 18px; float: left; margin-right: 8px; opacity: 0.7; }
    </style>
</head>
<body>
    <div id="map"></div>
    <script>
        var map = L.map('map').setView([55.3781, -3.4360], 6);
        L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
            attribution: '&copy; OpenStreetMap contributors'
        }).addTo(map);

        var STATUS_COLORS = {
            working:  '#2ecc71',
            partial:  '#f39c12',
            broken:   '#e74c3c'
        };

        var STATUS_LABELS = {
            working:  'Working',
            partial:  'Partially working',
            broken:   'Broken / not covered'
        };

        function style(feature) {
            var status = feature.properties.coverage_status || 'none';
            return {
                fillColor: STATUS_COLORS[status] || STATUS_COLORS.none,
                weight: 1,
                opacity: 1,
                color: 'white',
                fillOpacity: 0.6
            };
        }

        function popupText(props) {
            var status = props.coverage_status || 'none';
            var label = STATUS_LABELS[status] || 'Unknown';
            var text = '<strong>' + props.LAD25NM + '</strong><br>' + label;
            if (props.pass_rate !== undefined) {
                text += ' (' + props.pass_rate + '% pass rate)';
            }
            return text;
        }

        fetch('/static/coverage.geojson')
            .then(res => res.json())
            .then(data => {
                L.geoJson(data, {
                    style: style,
                    onEachFeature: function(feature, layer) {
                        layer.bindPopup(popupText(feature.properties));
                    }
                }).addTo(map);
            });

        var legend = L.control({position: 'bottomright'});
        legend.onAdd = function (map) {
            var div = L.DomUtil.create('div', 'info legend');
            Object.keys(STATUS_COLORS).forEach(function(key) {
                div.innerHTML += '<i style="background: ' + STATUS_COLORS[key] + '"></i> ' + STATUS_LABELS[key] + '<br>';
            });
            return div;
        };
        legend.addTo(map);
    </script>
</body>
</html>
"""

    print(f"Writing {OUTPUT_MAP_HTML}...")
    with open(OUTPUT_MAP_HTML, "w") as f:
        f.write(map_html)

    print("Done!")


if __name__ == "__main__":
    main()
