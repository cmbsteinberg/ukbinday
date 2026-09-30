"""North Ayrshire: looks up bin collection dates by UPRN through its ArcGIS service."""

from __future__ import annotations

from dateutil import parser

from api.councils._base import Address, Collection, Http, Meta, Scraper

_API_URL = (
    "https://www.maps.north-ayrshire.gov.uk/arcgis/rest/services/AGOL/"
    "YourLocationLive/MapServer/8/query?f=json&outFields=*&returnDistinctValues=true"
    "&returnGeometry=false&spatialRel=esriSpatialRelIntersects&where=UPRN%20%3D%20%27{0}%27"
)
_BIN_TEXTS = (
    "BLUE_DATE_TEXT",
    "GREY_DATE_TEXT",
    "PURPLE_DATE_TEXT",
    "BROWN_DATE_TEXT",
)


class NorthAyrshire(Scraper):
    meta = Meta(
        title="North Ayrshire Council",
        url="https://www.north-ayrshire.gov.uk/",
        lads=("S12000021",),
        cases={
            "Test_001": {"uprn": "126043248"},
            "Test_002": {"uprn": "126021147"},
            "Test_003": {"uprn": "126091148"},
        },
    )
    requires = frozenset({"uprn"})

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        r = await http.get(_API_URL.format(address.need("uprn")), check=False)
        attributes = r.json()["features"][0]["attributes"]

        collections = []
        for item in _BIN_TEXTS:
            if item not in attributes:
                continue
            colour = item.split("_")[0].capitalize()
            try:
                day_text = "/".join(reversed(attributes[item].split("/")))
            except AttributeError:
                continue
            collections.append(Collection(parser.parse(day_text).date(), colour))
        return collections


SCRAPER = NorthAyrshire()
