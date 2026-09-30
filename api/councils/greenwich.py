"""Royal Greenwich: search by postcode and house number, then build collections from the returned schedule and council calendars."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, timedelta

from api.councils._base import (
    Address,
    AddressNotFound,
    Collection,
    Http,
    InputError,
    Meta,
    Scraper,
    UpstreamError,
    match_address,
    parse_date,
    soup,
)

_ADDRESS_SEARCH_URL = (
    "https://www.royalgreenwich.gov.uk/site/custom_scripts/apps/"
    "waste-collection/source.php"
)
_COLLECTION_URL = (
    "https://www.royalgreenwich.gov.uk/site/custom_scripts/apps/"
    "waste-collection/ajax-response-uprn.php"
)
_BLACK_TOP_URL = (
    "https://www.royalgreenwich.gov.uk/recycling-and-rubbish/bins-and-collections/"
    "black-top-bin-collections"
)
_BANK_HOLIDAY_URL = (
    "https://www.royalgreenwich.gov.uk/recycling-and-rubbish/bins-and-collections/"
    "bank-holiday-collection-dates"
)
_DAYS = ("MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY")
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:139.0) "
        "Gecko/20100101 Firefox/139.0"
    ),
}


async def _find_address(address: Address, http: Http) -> str:
    if address.postcode:
        term = address.postcode
        if address.house_number:
            term = f"{term} {address.house_number}"
        response = await http.get(_ADDRESS_SEARCH_URL, params={"term": term})
        candidates: list[str] = response.json()

        if not candidates:
            raise AddressNotFound(f"No Royal Greenwich address found for {term!r}")
        if len(candidates) == 1:
            return candidates[0]
        return match_address(address, candidates, text=lambda candidate: candidate)

    if address.label:
        return address.label
    raise InputError("Royal Greenwich needs a postcode or an address")


async def _black_top_next_date(
    http: Http,
    week_name: str,
    this_week_collection_date: date,
) -> date:
    response = await http.get(_BLACK_TOP_URL)
    page = soup(response.text)
    table = page.find("table")
    if table is None:
        raise UpstreamError("Royal Greenwich black top bin schedule has no table")

    headers = table.find_all("th")
    try:
        week_column_index = [header.get_text() for header in headers].index(week_name)
        row = table.find("tbody").find("tr")
        first_week_dates_range = row.find_all("td")[week_column_index].get_text()
    except (AttributeError, IndexError, ValueError) as exc:
        raise UpstreamError("Could not read Royal Greenwich black top bin schedule") from exc

    try:
        first_week_date = parse_date(first_week_dates_range.split(" to ")[0])
    except ValueError as exc:
        raise UpstreamError("Could not parse Royal Greenwich black top bin schedule") from exc

    first_week_collection_date = first_week_date + timedelta(
        this_week_collection_date.isoweekday() - 1
    )
    if (this_week_collection_date - first_week_collection_date).days % 14:
        return this_week_collection_date + timedelta(weeks=1)
    return this_week_collection_date


async def _bank_holiday_overrides(http: Http) -> Mapping[date, date]:
    response = await http.get(_BANK_HOLIDAY_URL)
    page = soup(response.text)
    table = page.find("table")
    if table is None or len(table.find_all("th")) < 2:
        return {}

    result: dict[date, date] = {}
    body = table.find("tbody")
    if body is None:
        return result

    for row in body.find_all("tr"):
        cells = row.find_all("td")
        if len(cells) < 2:
            continue
        try:
            from_date = parse_date(cells[0].get_text())
            to_date = (
                from_date
                if cells[1].get_text() == "Collections as normal"
                else parse_date(cells[1].get_text())
            )
        except ValueError:
            continue
        result[from_date] = to_date
    return result


class Greenwich(Scraper):
    meta = Meta(
        title="Royal Borough Of Greenwich",
        url="https://www.royalgreenwich.gov.uk/",
        lads=("E09000011",),
        cases={
            "address": {
                "house_number": "25",
                "street": "Tizzard Grove",
                "postcode": "SE3 9DH",
            },
            "houseNumber": {"postcode": "SE9 5AW", "house_number": "11"},
            "alternativeWeek": {
                "house_number": "32",
                "street": "Glenlyon Road",
                "postcode": "SE9 1AJ",
            },
        },
    )
    requires = frozenset()
    headers = _HEADERS

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        council_address = await _find_address(address, http)
        response = await http.get(_COLLECTION_URL, params={"address": council_address})
        if response.text == "ADDRESS_NOT_FOUND":
            raise AddressNotFound(f"No Royal Greenwich collection data for {council_address!r}")

        data = response.json()
        collection_day = data["Day"]
        black_top_bin_week = data["Frequency"]

        today = date.today()
        try:
            collection_day_index = _DAYS.index(collection_day.upper()) + 1
        except ValueError as exc:
            raise UpstreamError(f"Unknown Royal Greenwich collection day: {collection_day!r}") from exc
        this_week_collection_date = today + timedelta(
            (collection_day_index - today.isoweekday()) % 7
        )

        next_food_collection_date = await _black_top_next_date(
            http, black_top_bin_week, this_week_collection_date
        )
        bank_holiday_overrides = await _bank_holiday_overrides(http)

        def correct(day: date) -> date:
            return bank_holiday_overrides.get(day, day)

        weeks_to_generate = 10
        recycling_collections = [
            Collection(correct(this_week_collection_date + timedelta(weeks=i)), "recycling")
            for i in range(weeks_to_generate)
        ]
        garden_collections = [
            Collection(correct(this_week_collection_date + timedelta(weeks=i)), "garden")
            for i in range(weeks_to_generate)
        ]
        food_collections = [
            Collection(
                correct(next_food_collection_date + timedelta(weeks=i * 2)),
                "food",
            )
            for i in range(int(weeks_to_generate / 2))
        ]
        return recycling_collections + garden_collections + food_collections


SCRAPER = Greenwich()
