"""Runnymede: looks up collection dates from the bin-day page using a UPRN."""

from __future__ import annotations

from datetime import datetime

from api.councils._base import Address, Collection, Http, Meta, Scraper, soup

_API_URL = "https://www.runnymede.gov.uk/bin-collection-day"


class Runnymede(Scraper):
    meta = Meta(
        title="Runnymede Borough Council",
        url="https://www.runnymede.gov.uk",
        lads=("E07000212",),
        cases={
            "Acacia Close": {"uprn": "100061482004"},
            "Addlestone Library": {"uprn": "10002019806"},
        },
    )
    requires = frozenset({"uprn"})
    headers = {"user-agent": "Mozilla/5.0"}

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        r = await http.get(_API_URL, params={"address": address.need("uprn")})
        page = soup(r.text)

        collections = []
        for result in page.find_all("tr"):
            result_row = result.find_all("td")
            if len(result_row) >= 2:
                day = datetime.strptime(result_row[1].text, "%A, %d %B %Y").date()
                collection_text = result_row[0].text.strip()
                collections.append(Collection(day, collection_text))
        return collections


SCRAPER = Runnymede()
