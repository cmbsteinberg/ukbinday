"""Islington: fetches collections by postcode and UPRN, expanding weekly collection rules when needed."""

from __future__ import annotations

import re
from datetime import date, timedelta

from dateutil.parser import parse

from api.councils._base import (
    Address,
    Collection,
    Http,
    Meta,
    Scraper,
    UpstreamError,
    find_tag,
    soup,
)

_URL = "https://www.islington.gov.uk"
_RULE_RE = re.compile(r"^(.*?) - .*?collected every week on (.+?)\.?$", re.IGNORECASE)
_WEEKDAYS = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}
_WEEKS_AHEAD = 12


class Islington(Scraper):
    meta = Meta(
        title="Islington Council",
        url=_URL,
        lads=("E09000019",),
        cases={
            "Test_001": {"postcode": "n1 1xr", "uprn": "5300094897"},
            "Test_002": {"postcode": "N1 0DD", "uprn": "10001295652"},
            "Test_003": {"postcode": "N19 4TA", "uprn": "5300078702"},
        },
    )
    requires = frozenset({"postcode", "uprn"})
    transport = __import__("api.councils._base", fromlist=["Transport"]).Transport.CURL_CFFI

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        url = (
            f"{_URL}/your-area?Postcode={address.need('postcode')}"
            f"&Uprn={address.need('uprn')}"
        )
        response = await http.get(url)
        page = soup(response.text)

        heading = page.find(string="Waste and recycling collections")
        if heading is None:
            raise UpstreamError("Waste and recycling collections section not found")
        content = heading.find_next("div", class_="m-toggle-content")
        if content is None:
            raise UpstreamError("Waste and recycling collections content not found")

        entries: list[Collection] = []
        waste_table = content.find("table")
        if waste_table:
            for row in waste_table.find_all("tr"):
                waste_type = find_tag(row, "td").text.strip().split(",")[0].split(" - ")[0]
                collection_day = find_tag(row, "td").text.strip().split(",")[1].split(" on ")[1]
                entries.append(Collection(parse(collection_day).date(), waste_type))
            return entries

        today = date.today()
        seen: set[tuple[str, int]] = set()
        for li in content.find_all("li"):
            text = " ".join(li.get_text().split())
            match = _RULE_RE.match(text)
            if not match:
                continue
            waste_type = match.group(1).strip()
            days = [
                _WEEKDAYS[day.strip().lower()]
                for day in match.group(2).split(",")
                if day.strip().lower() in _WEEKDAYS
            ]
            for weekday in days:
                if (waste_type, weekday) in seen:
                    continue
                seen.add((waste_type, weekday))
                first = today + timedelta(days=(weekday - today.weekday()) % 7)
                for week in range(_WEEKS_AHEAD):
                    entries.append(
                        Collection(
                            date=first + timedelta(weeks=week),
                            type=waste_type,
                        )
                    )

        return entries


SCRAPER = Islington()
