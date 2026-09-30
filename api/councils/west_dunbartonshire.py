"""West Dunbartonshire: fetch collection dates from the bin-day page using a UPRN."""

from __future__ import annotations

from datetime import datetime

from api.councils._base import Address, Collection, Http, Meta, Scraper, soup, text_of

_API_URL = "https://www.west-dunbarton.gov.uk/recycling-and-waste/bin-collection-day"


class WestDunbartonshire(Scraper):
    meta = Meta(
        title="West Dunbartonshire Council",
        url="https://www.west-dunbarton.gov.uk",
        lads=("S12000039",),
        cases={
            "2/2 26 Kilbowie Road, Clydebank": {"uprn": "129040292"},
            "6A Victoria Street, Dumbarton": {"uprn": "129033978"},
            "8 Clairinsh, Balloch": {"uprn": "129491488"},
        },
    )
    requires = frozenset({"uprn"})
    headers = {"user-agent": "Mozilla/5.0"}

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        r = await http.get(_API_URL, params={"uprn": address.need("uprn")})
        page = soup(r.text)

        collections = []
        for item in page.find_all("div", class_="round-info"):
            schedule_date = text_of(item.find("span", class_="date-string"))
            schedule_type = text_of(item.find("div", class_="round-name"))
            collection_date = datetime.strptime(schedule_date, "%d %B %Y").date()
            schedule_type_lower = schedule_type.lower()

            if "bag" in schedule_type_lower or "blue" in schedule_type_lower:
                collections.append(Collection(collection_date, "BLUE"))
            if "caddy" in schedule_type_lower or "brown" in schedule_type_lower:
                collections.append(Collection(collection_date, "BROWN"))
            if "non-recyclable" in schedule_type_lower:
                collections.append(Collection(collection_date, "BLACK"))

        return collections


SCRAPER = WestDunbartonshire()
