"""North Northamptonshire: fetches a UPRN's bin collections from the council calendar API."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from api.councils._base import Address, Collection, Http, InputError, Meta, Scraper

API_URL = "https://cms.northnorthants.gov.uk/bin-collection-search/calendarevents"
API_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 6.1; Win64; x64)"}


class NorthNorthamptonshire(Scraper):
    meta = Meta(
        title="North Northamptonshire council",
        url="https://www.northnorthants.gov.uk/",
        lads=("E06000061",),
        cases={
            "100030987513": {"uprn": "100030987513"},
            "100030987514": {"uprn": "100030987514"},
            "10093005361": {"uprn": "10093005361"},
        },
    )
    requires = frozenset({"uprn"})
    headers = API_HEADERS

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        today = (
            int(
                datetime.now(UTC)
                .replace(hour=23, minute=59, second=59)
                .timestamp()
            )
            * 1000
        )
        dateforurl = datetime.now().strftime("%Y-%m-%d")
        dateforurl2 = (datetime.now() + timedelta(days=42)).strftime("%Y-%m-%d")

        response = await http.get(
            f"{API_URL}/{address.need('uprn')}/{dateforurl}/{dateforurl2}",
            check=False,
        )
        if response.status_code != 200:
            raise InputError("No bin data found for provided UPRN..")

        json_response = json.loads(response.text)
        output_json = [
            item
            for item in json_response
            if int("".join(filter(str.isdigit, item["start"]))) >= today
        ]

        collections = []
        for item in output_json:
            title = item["title"].lower()
            if "recycling" in title:
                bin_type = "Recycling"
            elif "garden" in title:
                bin_type = "Garden"
            elif "refuse" in title:
                bin_type = "General"
            elif "food" in title:
                bin_type = "Food"
            else:
                bin_type = title

            dateofbin = int("".join(filter(str.isdigit, item["start"])))
            day = datetime.fromtimestamp(dateofbin / 1000, UTC).date()
            collections.append(Collection(day, bin_type))

        return collections


SCRAPER = NorthNorthamptonshire()
