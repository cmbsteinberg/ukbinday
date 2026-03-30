import json
import pathlib

import httpx

LAD_LOOKUP_PATH = "api/data/lad_lookup.json"
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


def main():
    print("Loading LAD lookup...")
    with open(LAD_LOOKUP_PATH) as f:
        lad_lookup = json.load(f)

    covered_codes = {code for code, info in lad_lookup.items() if info["scraper_id"]}

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
        feature["properties"]["covered"] = lad_cd in covered_codes
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

        function getColor(covered) {
            return covered ? '#2ecc71' : '#e74c3c';
        }

        function style(feature) {
            return {
                fillColor: getColor(feature.properties.covered),
                weight: 1,
                opacity: 1,
                color: 'white',
                fillOpacity: 0.6
            };
        }

        fetch('/static/coverage.geojson')
            .then(res => res.json())
            .then(data => {
                L.geoJson(data, {
                    style: style,
                    onEachFeature: function(feature, layer) {
                        layer.bindPopup('<strong>' + feature.properties.LAD25NM + '</strong><br>' +
                                      (feature.properties.covered ? 'Covered' : 'Not Covered'));
                    }
                }).addTo(map);
            });

        var legend = L.control({position: 'bottomright'});
        legend.onAdd = function (map) {
            var div = L.DomUtil.create('div', 'info legend');
            div.innerHTML += '<i style="background: #2ecc71"></i> Covered<br>';
            div.innerHTML += '<i style="background: #e74c3c"></i> Not Covered<br>';
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
