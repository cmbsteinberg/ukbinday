"""East Dunbartonshire: fetches the UPRN-specific collection schedule from the council page."""

from __future__ import annotations

from datetime import datetime

from api.councils._base import Address, Collection, Http, Meta, Scraper, soup


class EastDunbartonshire(Scraper):
    meta = Meta(
        title="East Dunbartonshire Council",
        url="https://eastdunbarton.gov.uk",
        lads=("S12000045",),
        cases={
            "Test_001": {"uprn": "132020996"},
            "Test_002": {"uprn": "132040577"},
            "Test_003": {"uprn": "132020494"},
        },
    )
    requires = frozenset({"uprn"})

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        r = await http.get(
            "https://www.eastdunbarton.gov.uk/services/a-z-of-services/bins-waste-and-recycling/"
            f"bins-and-recycling/collections/?uprn={address.need('uprn')}"
        )
        page = soup(r.content)

        collections = []
        for tr in page.find_all("tr")[1:]:
            tds = tr.find_all("td")
            collections.append(
                Collection(
                    date=datetime.strptime(tds[1].text.strip().split(", ")[1], "%d %B %Y").date(),
                    type=tds[0].text.strip(),
                )
            )

        return collections


SCRAPER = EastDunbartonshire()
