"""Newcastle-under-Lyme: looks up the UPRN's bin schedule on the council website."""

from __future__ import annotations

from api.councils._base import (
    Address,
    Collection,
    Http,
    Meta,
    Scraper,
    parse_date,
    soup,
)

_URL = "https://www.newcastle-staffs.gov.uk"
_HEADERS = {"user-agent": "Mozilla/5.0"}


class NewcastleUnderLyme(Scraper):
    meta = Meta(
        title="Newcastle Under Lyme Borough Council",
        url=_URL,
        lads=("E07000195",),
        cases={
            "Test_001": {"uprn": "100031744129"},
            "Test_002": {"uprn": "100031726082"},
            "Test_003": {"uprn": "100031736973"},
        },
    )
    requires = frozenset({"uprn"})

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        r = await http.get(
            f"{_URL}/homepage/97/check-your-bin-day?uprn={address.need('uprn')}",
            headers=_HEADERS,
        )
        page = soup(r.text)

        rows = []
        for tr in page.find_all("tr"):
            cells = []
            for cell in tr.find_all("td"):
                cells.append(cell)
            rows.append(cells)
        rows.pop(0)  # get rid of empty table header

        collections = []
        for row in rows:
            for cell in row:
                if row.index(cell) == 0:
                    day = parse_date(cell.get_text())
                else:
                    bins = (
                        str(cell)
                        .replace("\n", "")
                        .replace("<td>", "")
                        .replace("</td>", "")
                        .split("<br/>")
                    )
                    for bin_type in bins[:-1]:
                        collections.append(Collection(day, bin_type.strip()))

        return collections


SCRAPER = NewcastleUnderLyme()
