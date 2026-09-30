"""Dundee City: fetches bin collections from the MyBins calendar using a UPRN."""

from __future__ import annotations

from datetime import datetime

from api.councils._base import Address, Collection, Http, Meta, Scraper

_API_URL = "https://www.dundee-mybins.co.uk/get_calendar.php"


class DundeeCity(Scraper):
    meta = Meta(
        title="Dundee City Council",
        url="https://www.dundeecity.gov.uk",
        lads=("S12000042",),
        cases={
            "Test_1": {"uprn": "9059046613"},
            "Test_2": {"uprn": "9059082280"},
            "Test_3": {"uprn": "9059060343"},
        },
    )
    requires = frozenset({"uprn"})

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        response = await http.get(_API_URL, params={"rn": address.need("uprn")})
        schedule = response.json()

        return [
            Collection(
                date=datetime.strptime(item["start"], "%Y-%m-%d").date(),
                type=item["title"],
            )
            for item in schedule
        ]


SCRAPER = DundeeCity()
