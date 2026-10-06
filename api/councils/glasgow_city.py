"""Glasgow City Council: fetch the UPRN's current calendar, then post back for the next month."""

from __future__ import annotations

import re
from datetime import datetime

from api.councils._base import (
    Address,
    Collection,
    Http,
    Meta,
    Scraper,
    find_tag,
    soup,
)

_API_URL = (
    "https://onlineservices.glasgow.gov.uk/forms/refuseandrecyclingcalendar/"
    "CollectionsCalendar.aspx?UPRN="
)


def _parse_bins(text: str) -> list[Collection]:
    page = soup(text)
    entries = []

    days = page.find_all("td", {"class": "CalendarDayStyle"})
    for day in days:
        bins = day.find_all("img")

        if len(bins) < 1:
            continue

        collection_date = datetime.strptime(
            day["title"].replace("today is ", ""), "%A, %d %B %Y"
        ).date()

        for bin_image in bins:
            bin_name = bin_image["title"].split()
            bin_type = f"{bin_name[0]} {bin_name[1]}"
            entries.append(Collection(date=collection_date, type=bin_type))

    return entries


class GlasgowCity(Scraper):
    meta = Meta(
        title="Glasgow City Council",
        url="https://www.glasgow.gov.uk/",
        lads=("S12000049",),
        cases={
            "test 1 - house": {"uprn": "906700099060"},
            "test 2 - flat": {"uprn": "906700335412"},
        },
    )
    requires = frozenset({"uprn"})

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        url = f"{_API_URL}{address.need('uprn')}"

        response = await http.get(url)
        entries = _parse_bins(response.text)

        page = soup(response.text)
        next_link = page.find("a", title="Go to the next month")
        if next_link is not None and len(next_link) > 0:
            match = re.search(r"__doPostBack\('(.*?)','(.*?)'", next_link["href"])
            data = {
                "__EVENTTARGET": match.group(1),
                "__EVENTARGUMENT": match.group(2),
                "__EVENTVALIDATION": find_tag(page, "input", id="__EVENTVALIDATION")["value"],
                "__VIEWSTATE": find_tag(page, "input", id="__VIEWSTATE")["value"],
            }
            response = await http.post(url, data=data)
            entries.extend(_parse_bins(response.text))

        return entries


SCRAPER = GlasgowCity()
