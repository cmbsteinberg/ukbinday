"""Dorset: queries four per-UPRN service endpoints for the next collection dates."""

from __future__ import annotations

from datetime import datetime

from api.councils._base import Address, Collection, Http, Meta, Scraper

_API_URLS = {
    "Recycling": "https://geoapi.dorsetcouncil.gov.uk/v1/Services/recyclingday/{uprn}",
    "Rubbish": "https://geoapi.dorsetcouncil.gov.uk/v1/Services/refuseday/{uprn}",
    "Garden Waste": "https://geoapi.dorsetcouncil.gov.uk/v1/Services/gardenwasteday/{uprn}",
    "Food Waste": "https://geoapi.dorsetcouncil.gov.uk/v1/Services/foodwasteday/{uprn}",
}


class Dorset(Scraper):
    meta = Meta(
        title="Dorset Council",
        url="https://www.dorsetcouncil.gov.uk/",
        lads=("E06000059",),
        cases={
            "Test_001": {"uprn": "100040606062"},
            "Test_002": {"uprn": "100040606087"},
            "Test_003": {"uprn": "100040606071"},
        },
    )
    requires = frozenset({"uprn"})

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        uprn = address.need("uprn")
        collections = []
        for bin_type, url in _API_URLS.items():
            r = await http.get(url.format(uprn=uprn))
            json_data = r.json()
            if not json_data["values"]:
                continue  # This service is not used at the address.
            day = datetime.strptime(
                json_data["values"][0]["dateNextVisit"], "%Y-%m-%d"
            ).date()
            collections.append(Collection(day, bin_type))
        return collections


SCRAPER = Dorset()
