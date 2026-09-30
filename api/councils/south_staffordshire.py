"""South Staffordshire: fetches the UPRN-specific collection page and parses its HTML."""

from __future__ import annotations

from datetime import datetime

from api.councils._base import Address, Collection, Http, Meta, Scraper, soup


class SouthStaffordshire(Scraper):
    meta = Meta(
        title="South Staffordshire Council",
        url="https://sstaffs.gov.uk/",
        lads=("E07000196",),
        cases={
            "Test_001": {"uprn": "100031831923"},
            "Test_002": {"uprn": "100031811736"},
            "Test_003": {"uprn": "100031799974"},
        },
    )
    requires = frozenset({"uprn"})
    headers = {"user-agent": "Mozilla/5.0"}

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        r = await http.get(
            f"https://www.sstaffs.gov.uk/where-i-live?objectId={address.need('uprn')}"
        )
        page = soup(r.content)

        entries: list[Collection] = []

        next_date = page.find("p", {"class": "collection-date"})
        next_bin = page.find("p", {"class": "collection-type"})
        if next_date and next_bin:
            date_text = next_date.get_text(strip=True)
            type_text = next_bin.get_text(strip=True)
            entries.append(
                Collection(
                    date=datetime.strptime(date_text, "%A, %d %B %Y").date(),
                    type=type_text,
                )
            )

        trs = page.find_all("tr")
        for tr in trs[1:]:
            tds = tr.find_all("td")
            if len(tds) < 2:
                continue
            waste_type = tds[0].get_text(strip=True)
            waste_date = tds[1].get_text(strip=True)
            entries.append(
                Collection(
                    date=datetime.strptime(waste_date, "%A, %d %B %Y").date(),
                    type=waste_type,
                )
            )

        return entries


SCRAPER = SouthStaffordshire()
