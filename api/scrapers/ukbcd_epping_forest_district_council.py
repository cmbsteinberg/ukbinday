import httpx
from api.compat.ukbcd.common import *
from api.compat.ukbcd.get_bin_data import AbstractGetBinDataClass
from api.compat import httpx_helpers as _http


class CouncilClass(AbstractGetBinDataClass):
    async def parse_data(self, page: str, **kwargs) -> dict:
        postcode = kwargs.get("postcode", "")
        data = {"bins": []}

        # Use postcodes.io to get BNG eastings/northings for the postcode
        pc_clean = postcode.replace(" ", "")
        geo_resp = await _http.get(f"https://api.postcodes.io/postcodes/{pc_clean}")
        geo_resp.raise_for_status()
        geo_data = geo_resp.json()
        if geo_data.get("status") != 200 or not geo_data.get("result"):
            raise ValueError(f"Could not geocode postcode {postcode}")

        eastings = geo_data["result"]["eastings"]
        northings = geo_data["result"]["northings"]

        # Query the ArcGIS feature layer directly with a point geometry
        feature_url = (
            "https://services-eu1.arcgis.com/SDWAhoV6ICvQHz6h/arcgis/rest/services/"
            "Website_WasteCollectionRoutes/FeatureServer/0/query"
        )
        params = {
            "geometry": f'{{"x":{eastings},"y":{northings},"spatialReference":{{"wkid":27700}}}}',
            "geometryType": "esriGeometryPoint",
            "spatialRel": "esriSpatialRelIntersects",
            "outFields": "WasteCollectionDates_ResidualDa,WasteCollectionDates_RecyclingD,WasteCollectionDates_FoodAndGar",
            "returnGeometry": "false",
            "f": "json",
        }
        resp = await _http.get(feature_url, params=params)
        resp.raise_for_status()
        result = resp.json()

        features = result.get("features", [])
        if not features:
            raise ValueError(f"No waste collection zone found for postcode {postcode}")

        attrs = features[0]["attributes"]

        # Map field names to bin types
        bin_map = {
            "WasteCollectionDates_ResidualDa": "Black Bin",
            "WasteCollectionDates_RecyclingD": "Blue Box and Recycling Sack",
            "WasteCollectionDates_FoodAndGar": "Green-lidded Bin",
        }

        for field, bin_type in bin_map.items():
            date_str = attrs.get(field)
            if date_str:
                try:
                    parsed = datetime.strptime(date_str.strip(), "%d/%m/%Y")
                    data["bins"].append(
                        {
                            "type": bin_type,
                            "collectionDate": parsed.strftime(date_format),
                        }
                    )
                except ValueError:
                    continue

        data["bins"].sort(
            key=lambda x: datetime.strptime(x.get("collectionDate"), date_format)
        )

        return data


# --- Adapter for Project API ---
from api.compat.hacs import Collection  # type: ignore[attr-defined]

TITLE = "Epping Forest"
URL = "https://eppingforestdc.maps.arcgis.com/apps/instant/lookup/index.html?appid=bfca32b46e2a47cd9c0a84f2d8cdde17&find=IG9%206EP"
TEST_CASES = {}


class Source:
    def __init__(self, postcode: str | None = None):
        self.postcode = postcode
        self._scraper = CouncilClass()

    async def fetch(self) -> list[Collection]:
        from datetime import datetime

        kwargs = {}
        if self.postcode: kwargs['postcode'] = self.postcode

        data = await self._scraper.parse_data("", **kwargs)

        entries = []
        if isinstance(data, dict) and "bins" in data:
            for item in data["bins"]:
                bin_type = item.get("type")
                date_str = item.get("collectionDate")
                if not bin_type or not date_str:
                    continue
                try:
                    if "-" in date_str:
                        dt = datetime.strptime(date_str, "%Y-%m-%d").date()
                    elif "/" in date_str:
                        dt = datetime.strptime(date_str, "%d/%m/%Y").date()
                    else:
                        continue
                    entries.append(Collection(date=dt, t=bin_type, icon=None))
                except ValueError:
                    continue
        return entries
