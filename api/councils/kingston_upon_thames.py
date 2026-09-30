"""Kingston upon Thames: search by postcode, select the matching property, then poll its waste schedule."""

from __future__ import annotations

import asyncio
import re
from datetime import date

from bs4 import Tag

from api.councils._base import (
    Address,
    Collection,
    Http,
    Meta,
    Scraper,
    Transport,
    match_address,
    parse_date,
    soup,
    text_of,
)

_WASTE_URL = "https://waste-services.kingston.gov.uk/waste"
_DATE_PATTERN = re.compile(
    r"(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),?\s+"
    r"(\d+)(?:st|nd|rd|th)?\s+(\w+)"
)


class KingstonUponThames(Scraper):
    meta = Meta(
        title="Kingston upon Thames Council",
        url="https://www.kingston.gov.uk",
        lads=("E09000021",),
        cases={
            "Test_001": {
                "postcode": "KT3 3EG",
                "house_number": "25",
                "street": "Beechcroft Avenue",
            }
        },
    )
    requires = frozenset({"postcode"})
    transport = Transport.CURL_CFFI

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        await http.get(_WASTE_URL)
        r = await http.post(_WASTE_URL, data={"postcode": address.need("postcode")})
        page = soup(r.text)

        select = page.find("select", attrs={"name": "address"})
        options = [
            option
            for option in select.find_all("option")
            if isinstance(option, Tag)
            and isinstance(option.get("value"), str)
            and option.get("value")
        ] if isinstance(select, Tag) else []

        selected = match_address(address, options, text=text_of)
        property_id = str(selected["value"])

        # The property page is a loading stub that meta-refreshes to
        # ?page_loading=1; that URL only returns the schedule once the
        # property page itself has been requested in the same session.
        page_url = f"{_WASTE_URL}/{property_id}"
        await http.get(page_url)
        for _ in range(4):
            r = await http.get(f"{page_url}?page_loading=1")
            if "waste-service-grid" in r.text:
                break
            await asyncio.sleep(2)

        return _parse_schedule(r.text)


def _parse_schedule(html: str) -> list[Collection]:
    page = soup(html)
    entries: list[Collection] = []

    for grid in page.find_all("div", class_="waste-service-grid"):
        h3 = grid.find("h3", class_="waste-service-name")
        if not isinstance(h3, Tag):
            continue
        service_name = h3.get_text(strip=True)

        dl = grid.find("dl", class_="govuk-summary-list")
        if not isinstance(dl, Tag):
            continue

        for row in dl.find_all("div", class_="govuk-summary-list__row"):
            dt = row.find("dt")
            if not isinstance(dt, Tag) or "next collection" not in dt.get_text(strip=True).lower():
                continue
            dd = row.find("dd")
            if not isinstance(dd, Tag):
                continue

            date_text = re.sub(r"\(.*?\)", "", dd.get_text(strip=True)).strip()
            match = _DATE_PATTERN.search(date_text)
            if not match:
                continue

            try:
                collection_date: date = parse_date(match.group(0))
            except ValueError:
                continue

            entries.append(Collection(collection_date, service_name))

    return entries


SCRAPER = KingstonUponThames()
