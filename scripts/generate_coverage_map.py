import json
import pathlib

import httpx
import ibis

# Paths
LAD_LOOKUP_PATH = "api/data/lad_lookup.json"
GEOJSON_URL = "https://services1.arcgis.com/ESMARspQHYMw9BZ9/arcgis/rest/services/LAD_MAY_2025_UK_BUC/FeatureServer/0/query?outFields=*&where=1%3D1&f=geojson"
OUTPUT_DIR = pathlib.Path("api/static")
OUTPUT_GEOJSON = OUTPUT_DIR / "coverage.geojson"
OUTPUT_MAP_HTML = OUTPUT_DIR / "coverage_map.html"

def main():
    # Fetch data
    print("Fetching LAD lookup...")
    with open(LAD_LOOKUP_PATH) as f:
        lad_lookup = json.load(f)

    print("Fetching UK boundaries...")
    try:
        response = httpx.get(GEOJSON_URL, timeout=60.0)
        response.raise_for_status()
        geojson_data = response.json()
    except Exception as e:
        print(f"Error fetching GeoJSON: {e}")
        return

    # Use ibis/duckdb for manipulation

    # Prepare coverage data for ibis
    coverage_list = []
    for code, info in lad_lookup.items():
        coverage_list.append({
            "LAD25CD": code,
            "covered": info["scraper_id"] is not None
        })

    coverage_table = ibis.memtable(coverage_list)

    # Extract properties from GeoJSON features to a table
    features = geojson_data["features"]
    properties_list = [f["properties"] for f in features]
    properties_table = ibis.memtable(properties_list)

    # Join on LAD25CD
    # Note: ArcGIS GeoJSON uses LAD25CD as seen in inspection
    result_table = properties_table.join(coverage_table, "LAD25CD", how="left")
    # Fill nulls in 'covered' as False
    result_table = result_table.mutate(covered=result_table.covered.fill_null(False))

    # Execute and get results back as dictionaries
    print("Joining data...")
    updated_properties_df = result_table.execute()
    updated_properties = updated_properties_df.to_dict('records')

    # Map LAD25CD to its updated properties for easy lookup
    prop_map = {p["LAD25CD"]: p for p in updated_properties}

    # Update GeoJSON features
    for feature in features:
        lad_cd = feature["properties"]["LAD25CD"]
        if lad_cd in prop_map:
            feature["properties"] = prop_map[lad_cd]
        else:
            # If not in lookup, default to not covered
            feature["properties"]["covered"] = False

    # Write updated GeoJSON
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Writing {OUTPUT_GEOJSON}...")
    with open(OUTPUT_GEOJSON, "w") as f:
        json.dump(geojson_data, f)

    # Generate Map HTML
    map_html = """
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
            attribution: '© OpenStreetMap contributors'
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
                                      (feature.properties.covered ? '✅ Covered' : '❌ Not Covered'));
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
