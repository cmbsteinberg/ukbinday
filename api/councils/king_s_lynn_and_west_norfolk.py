"""King's Lynn & West Norfolk: set session cookies from the UPRN, then parse the calendar page."""

from __future__ import annotations

import re
from datetime import datetime

from api.councils._base import Address, Collection, Http, Meta, Scraper, soup

_PAGE = "https://www.west-norfolk.gov.uk/info/20174/bins_and_recycling_collection_dates"
_CALENDAR = "https://www.west-norfolk.gov.uk/bincollectionscalendar"
_HEADERS = {"user-agent": "Mozilla/5.0"}


class KingsLynnAndWestNorfolk(Scraper):
    meta = Meta(
        title="Borough Council of King's Lynn & West Norfolk",
        url="https://www.west-norfolk.gov.uk",
        lads=("E07000146",),
        cases={
            "Test_001": {"uprn": "100090969937"},
            "Test_002": {"uprn": "100090989776"},
            "Test_003": {"uprn": "10000021270"},
        },
    )
    requires = frozenset({"uprn"})
    headers = _HEADERS

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        uprn = address.need("uprn").zfill(12)

        await http.get(_PAGE)
        session_id = http.cookies.get("PHPSESSID")
        if session_id is not None:
            http.cookies.set("bcklwn_store", session_id)
        http.cookies.set("bcklwn_uprn", uprn)

        await http.get(_PAGE)
        response = await http.get(_CALENDAR)

        collections = []
        for item in soup(response.text).find_all("div", {"class": "cldr_month"}):
            month = item.find("h2")
            dates = item.find_all("td", {"class": re.compile(" (recycling|refuse|garden)")})
            for day_cell in dates:
                classes = day_cell.attrs.get("class")
                for bin_type in classes[2:]:
                    day = day_cell.text + " " + month.text
                    collections.append(
                        Collection(
                            date=datetime.strptime(day, "%d %B %Y").date(),
                            type=bin_type,
                        )
                    )
        return collections


SCRAPER = KingsLynnAndWestNorfolk()
