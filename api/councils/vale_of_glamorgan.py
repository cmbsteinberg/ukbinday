"""Vale of Glamorgan: fetches a UPRN's waste data, then reads residual and garden calendars."""

from __future__ import annotations

import json
import random
from datetime import date, datetime, timedelta

from api.councils._base import (
    Address,
    Collection,
    Http,
    InputError,
    Meta,
    Scraper,
    soup,
)

_API_URL = "https://myvale.valeofglamorgan.gov.uk/getdata.aspx"
_WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


async def _calendar_collections(http: Http, calendar_url: str, bin_type: str) -> list[Collection]:
    response = await http.get(calendar_url)
    page = soup(response.text)
    entries: list[Collection] = []
    for row in page.select("table tr"):
        cells = row.select("td")
        if len(cells) != 2:
            continue

        months = cells[0].text.strip()
        days = cells[1].text.strip().replace("and", ",").split(",")
        for day in days:
            day = day.strip()
            if not day.isdigit():
                continue
            collection_date = datetime.strptime(f"{day} {months}", "%d %B %Y").date()
            entries.append(Collection(collection_date, bin_type))
    return entries


class ValeOfGlamorgan(Scraper):
    meta = Meta(
        title="Vale of Glamorgan Council",
        url="https://valeofglamorgan.gov.uk/",
        lads=("W06000014",),
        cases={
            "CF62 7JP": {"uprn": "64003486"},
            "CF32 0PW": {"uprn": "64017161"},
        },
    )
    requires = frozenset({"uprn"})

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        timestamp = str(int(datetime.now().timestamp() * 1000))
        random_callback_number = str(random.randint(10000000000000000000, 99999999999999999999))
        params = {
            "RequestType": "LocalInfo",
            "ms": "ValeOfGlamorgan/AllMaps",
            "group": "Waste|new_refuse",
            "type": "jsonp",
            "callback": "AddressInfoCallback",
            "uid": address.need("uprn"),
            "import": f"jQuery{random_callback_number}_{timestamp}",
            "_": timestamp,
        }

        response = await http.get(_API_URL, params=params)
        text = response.text.replace("AddressInfoCallback(", "").rstrip(");")
        data = json.loads(text)["Results"]["waste"]

        recycling_food = data["recycling_food"]
        if recycling_food not in _WEEKDAYS:
            raise InputError(f"Unknown recycling_food: {recycling_food}")

        next_recycling_food = date.today()
        while next_recycling_food.weekday() != _WEEKDAYS.index(recycling_food):
            next_recycling_food += timedelta(days=1)

        collections = [
            Collection(next_recycling_food + timedelta(weeks=i), "Recycling")
            for i in range(10)
        ]
        collections.extend(
            Collection(next_recycling_food + timedelta(weeks=i), "Food")
            for i in range(10)
        )
        collections.extend(
            await _calendar_collections(http, data["residual_calendar_url"], "Trash")
        )
        collections.extend(
            await _calendar_collections(http, data["green_calendar_url"], "Garden")
        )
        return collections


SCRAPER = ValeOfGlamorgan()
