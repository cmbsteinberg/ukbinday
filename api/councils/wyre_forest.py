"""Wyre Forest: postcode-area street lookup for refuse collections, with optional garden-waste details."""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta

from api.councils._base import (
    Address,
    Collection,
    Http,
    Meta,
    Scraper,
    UpstreamError,
    soup,
)

_API_URLS = {
    "waste": "https://forms.wyreforestdc.gov.uk/querybin.asp",
    "garden_waste": "https://forms.wyreforestdc.gov.uk/GardenWasteChecker/Home/Details",
}
_DAYS = ["MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY"]

# Next Rubbish Collection
_REGEX_GET_BIN_TYPE = re.compile(r"Next (.*?) Collection")
# collection is on a WEDNESDAY and will be collected on the same week as your rubbish bin collection
_REGEX_GET_GARDEN_DAY = re.compile(
    r"collection is on a\s*(.*?)\s*and will be collected on the same week as"
)
_REGEX_GET_GARDEN_SAME_WEEK_AS = re.compile(
    r"collected on the same week as your\s*(.*?)\s*(bin)?\s*collection"
)


def _get_date_by_weekday(weekday: str) -> date:
    if weekday.strip().upper() == "TODAY":
        return date.today()
    if weekday.strip().upper() == "TOMORROW":
        return date.today() + timedelta(days=1)

    this_week = re.match(r"This (.*?)$", weekday, re.IGNORECASE)
    next_week = re.match(r"Next (.*?)$", weekday, re.IGNORECASE)
    if this_week:
        weekday_idx = _DAYS.index(this_week.group(1).upper())
        offset = 0
    elif next_week:
        weekday_idx = _DAYS.index(next_week.group(1).upper())
        offset = 7
    else:
        try:
            return datetime.strptime(weekday.strip(), "%d %B %Y").date()
        except ValueError:
            pass
        try:
            return datetime.strptime(weekday.strip(), "%d %b %Y").date()
        except ValueError:
            pass
        raise ValueError(f"Invalid weekday: {weekday}")

    day = date.today() + timedelta(days=offset)
    while day.weekday() != weekday_idx:
        day += timedelta(days=1)
    return day


def _predict_next_collections(first_date: date, day_interval: int = 14) -> list[date]:
    return [first_date + timedelta(days=i * day_interval) for i in range(5)]


class WyreForest(Scraper):
    meta = Meta(
        title="Wyre Forest District Council",
        url="https://www.wyreforestdc.gov.uk",
        lads=("E07000239",),
        cases={
            "2 Kinver Avenue, Kidderminster": {
                "street": "hilltop avenue",
                "town": "BEWDLEY",
                "garden_cutomer": "308072",
            },
        },
    )
    requires = frozenset({"street", "town"})

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        street = address.need("street").upper().strip()
        town = address.need("town").upper().strip()
        garden_customer = address.get("garden_cutomer")
        if garden_customer:
            garden_customer = garden_customer.strip()

        params = {
            "txtStreetName": street,
            "select": "yes",
            "town": town,
        }
        r = await http.post(_API_URLS["waste"], params=params)
        page = soup(r.text)
        collection_day_header = page.find("p", string="Collection Day")

        if collection_day_header is None:
            raise UpstreamError("Could not find collection day header")
        collection_day_table = collection_day_header.find_parent("table")
        if collection_day_table is None:
            raise UpstreamError("Could not find collection day table")
        collection_day_rows = collection_day_table.find_all("tr")
        if len(collection_day_rows) != 2:
            raise UpstreamError("Could not find collection day rows")

        headings = [cell.text.strip() for cell in collection_day_rows[0].find_all("td")]
        values = [cell.text.strip() for cell in collection_day_rows[1].find_all("td")]

        collections: list[Collection] = []
        type_to_day: dict[str, str] = {}
        for heading, value in zip(headings, values, strict=False):
            bin_type_match = _REGEX_GET_BIN_TYPE.match(heading)
            if not bin_type_match:
                continue

            bin_type = bin_type_match.group(1)
            type_to_day[bin_type.lower()] = value
            try:
                collection_dates = _predict_next_collections(_get_date_by_weekday(value))
            except ValueError as exc:
                raise UpstreamError(f"Could not parse collection day: {value}") from exc
            collections.extend(Collection(day, bin_type) for day in collection_dates)

        if garden_customer:
            garden_response = await http.post(
                _API_URLS["garden_waste"],
                data={"CUST_No": garden_customer},
            )
            garden_page = soup(garden_response.text)

            garden_day = _REGEX_GET_GARDEN_DAY.search(garden_page.text)
            same_week_as = _REGEX_GET_GARDEN_SAME_WEEK_AS.search(garden_page.text)
            if garden_day is None or same_week_as is None:
                raise UpstreamError("Could not find garden waste collection days")

            try:
                relevant_collection_date = _get_date_by_weekday(
                    type_to_day[same_week_as.group(1).lower()]
                )
                monday_of_garden_week = relevant_collection_date - timedelta(
                    days=relevant_collection_date.weekday()
                )
                garden_collection_day = monday_of_garden_week + timedelta(
                    _DAYS.index(garden_day.group(1).upper())
                )
            except (KeyError, ValueError) as exc:
                raise UpstreamError("Could not parse garden waste collection days") from exc

            collections.extend(
                Collection(day, "Garden waste")
                for day in _predict_next_collections(garden_collection_day)
            )

        return collections


SCRAPER = WyreForest()
