"""City of Edinburgh: resolve a street, look up its collection calendars, and generate dates."""

from __future__ import annotations

import re
from datetime import datetime, timedelta

from api.councils._base import (
    Address,
    AddressNotFound,
    Collection,
    Http,
    InputError,
    Meta,
    Scraper,
    UpstreamError,
    soup,
    text_of,
)

_DIRECTORY_SEARCH = "https://www.edinburgh.gov.uk/directory/search"
_NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
_HEADERS = {
    "User-Agent": "UKBinCollectionData/1.0 (+https://github.com/robbrad/UKBinCollectionData)"
}
_DAYS_OF_WEEK = (
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
)
_CALENDAR_CODES = {
    "Mon": "Monday",
    "Tue": "Tuesday",
    "Wed": "Wednesday",
    "Thu": "Thursday",
    "Fri": "Friday",
    "Sat": "Saturday",
    "Sun": "Sunday",
}


def _extract_street_from_paon(paon: str | None) -> str | None:
    """Extract a street name from a PAON such as '157 Morningside Road'."""
    if not paon:
        return None
    stripped = re.sub(r"^\d+[a-zA-Z]?\s+", "", paon.strip())
    if stripped and stripped != paon.strip():
        return stripped
    if not paon.strip()[0].isdigit():
        return paon.strip()
    return None


async def _resolve_street(
    postcode: str | None, paon: str | None, http: Http
) -> str | None:
    """Use the PAON when possible, otherwise geocode the postcode and reverse lookup."""
    street = _extract_street_from_paon(paon)
    if street:
        return street
    if postcode is None:
        return None

    try:
        pc_clean = postcode.replace(" ", "")
        pc_resp = await http.get(
            f"https://api.postcodes.io/postcodes/{pc_clean}",
            timeout=10,
            check=False,
        )
        if pc_resp.status_code == 200:
            pc_data = pc_resp.json()
            result = pc_data.get("result")
            if pc_data.get("status") == 200 and result:
                rev_resp = await http.get(
                    _NOMINATIM_URL.replace("/search", "/reverse"),
                    params={
                        "lat": result["latitude"],
                        "lon": result["longitude"],
                        "format": "json",
                        "addressdetails": 1,
                    },
                    timeout=10,
                    check=False,
                )
                if rev_resp.status_code == 200:
                    addr = rev_resp.json().get("address", {})
                    road = addr.get("road") or addr.get("street")
                    if road:
                        return road
    except UpstreamError:
        pass  # best-effort geocoding: without a street the caller reports the address as not found
    return None


async def _search_directory(street_name: str, record: int, http: Http) -> list[tuple[str, str]]:
    """Search Edinburgh's waste collection directory for a street."""
    resp = await http.get(
        _DIRECTORY_SEARCH,
        params={"directoryID": str(record), "keywords": street_name},
        timeout=15,
    )
    results: list[tuple[str, str]] = []
    for link in soup(resp.text).select("a.list__link"):
        href = link.get("href", "")
        if "/directory-record/" in href:
            if not href.startswith("http"):
                href = "https://www.edinburgh.gov.uk" + href
            results.append((href, text_of(link)))
    return results


async def _get_best_url(street_name: str, record: int, http: Http) -> str:
    """Choose the best-matching street record."""
    records = await _search_directory(street_name, record, http)
    if not records:
        raise AddressNotFound(
            f"No Edinburgh collection records found for street {street_name!r}"
        )

    best_url = records[0][0]
    for url, title in records:
        if title.upper() == street_name.upper():
            best_url = url
            break
    return best_url


async def _get_calendar_code(record_url: str, http: Http) -> str | None:
    """Extract the calendar code from a directory record."""
    resp = await http.get(record_url, timeout=15)
    for dt in soup(resp.text).find_all("dt"):
        if "calendar code" in text_of(dt).lower():
            dd = dt.find_next_sibling("dd")
            if dd:
                return text_of(dd)
    return None


async def _get_collection_day(record_url: str, http: Http) -> str | None:
    """Extract the collection day from a directory record."""
    resp = await http.get(record_url, timeout=15)
    for dt in soup(resp.text).find_all("dt"):
        if "collection day" in text_of(dt).lower():
            dd = dt.find_next_sibling("dd")
            if dd:
                return text_of(dd)
    return None


async def _get_garden_calendar_code(record_url: str, http: Http) -> str | None:
    """Extract the garden calendar code from a directory record."""
    resp = await http.get(record_url, timeout=15)
    for dt in soup(resp.text).find_all("dt"):
        if "calendar" in text_of(dt).lower():
            dd = dt.find_next_sibling("dd")
            if dd:
                cal_link = dd.find("a", href=True)
                if cal_link:
                    cal_url = cal_link["href"].strip()
                    cal_target = "garden-waste-calendar-"
                    target_idx = cal_url.find(cal_target)
                    if target_idx >= 0:
                        return cal_url[target_idx + len(cal_target) :]
    return None


def _parse_calendar_code(code: str) -> tuple[str | None, int | None]:
    """Parse a code such as 'Tue_2' into a weekday and zero-based week index."""
    match = re.match(r"(Mon|Tue|Wed|Thu|Fri|Sat|Sun)_(\d)", code)
    if not match:
        return None, None
    day_name = _CALENDAR_CODES.get(match.group(1))
    return day_name, int(match.group(2)) - 1


def _parse_garden_calendar_code(code: str) -> tuple[str | None, int | None]:
    """Parse a code such as 'friday-1' into a weekday and zero-based week index."""
    match = re.match(
        r"(monday|tuesday|wednesday|thursday|friday|saturday|sunday)-(\d)",
        code,
    )
    if not match:
        return None, None
    return match.group(1).capitalize(), int(match.group(2)) - 1


async def _get_three_bins(
    street_name: str, http: Http
) -> tuple[datetime, datetime, datetime, int]:
    """Get the recycling, glass and refuse start dates and weekday offset."""
    best_url = await _get_best_url(street_name, 10251, http)
    calendar_code = await _get_calendar_code(best_url, http)
    if not calendar_code:
        raise AddressNotFound(f"No calendar code found for {street_name!r} at {best_url}")

    day_name, week_index = _parse_calendar_code(calendar_code)
    if not day_name or week_index is None:
        raise AddressNotFound(f"Could not parse calendar code {calendar_code!r}")

    offset_days = _DAYS_OF_WEEK.index(day_name)
    if week_index == 0:
        recycling_start = datetime(2025, 11, 3)
        glass_start = datetime(2025, 11, 3)
        refuse_start = datetime(2025, 11, 10)
    else:
        recycling_start = datetime(2025, 11, 10)
        glass_start = datetime(2025, 11, 10)
        refuse_start = datetime(2025, 11, 3)

    return recycling_start, glass_start, refuse_start, offset_days


async def _get_food_bin(street_name: str, http: Http) -> int:
    """Get the weekday offset for weekly food waste collections."""
    best_url = await _get_best_url(street_name, 10248, http)
    collection_day = await _get_collection_day(best_url, http)
    if not collection_day:
        raise AddressNotFound(
            f"No food waste collection day found for {street_name!r} at {best_url}"
        )
    try:
        return _DAYS_OF_WEEK.index(collection_day)
    except ValueError as exc:
        raise AddressNotFound(
            f"Unrecognised food waste collection day {collection_day!r}"
        ) from exc


async def _get_garden_bin(
    street_name: str, http: Http
) -> tuple[datetime, int, datetime, datetime]:
    """Get the garden waste schedule and its holiday break."""
    best_url = await _get_best_url(street_name, 10250, http)
    calendar_code = await _get_garden_calendar_code(best_url, http)
    if not calendar_code:
        raise AddressNotFound(f"No calendar code found for {street_name!r} at {best_url}")

    day_name, week_index = _parse_garden_calendar_code(calendar_code)
    if not day_name or week_index is None:
        raise AddressNotFound(f"Could not parse garden calendar code {calendar_code!r}")

    garden_offset_day = _DAYS_OF_WEEK.index(day_name)
    garden_start = datetime(2025, 11, 10) if week_index == 0 else datetime(2025, 11, 3)
    no_garden_waste_start = datetime(2025, 12, 15)
    no_garden_waste_end = datetime(2026, 1, 11)
    return garden_start, garden_offset_day, no_garden_waste_start, no_garden_waste_end


class CityOfEdinburgh(Scraper):
    meta = Meta(
        title="City of Edinburgh",
        url="https://www.edinburgh.gov.uk",
        lads=("S12000036",),
        cases={},
    )
    requires = frozenset()
    headers = _HEADERS

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        street_name = await _resolve_street(address.postcode, address.first_line, http)
        if not street_name:
            raise InputError(
                f"Could not resolve a street name for {address.first_line or address.label or 'the address'}"
            )

        recycling_start, glass_start, refuse_start, three_offset_days = (
            await _get_three_bins(street_name, http)
        )
        food_offset_day = await _get_food_bin(street_name, http)
        (
            garden_start,
            garden_offset_day,
            no_garden_waste_start,
            no_garden_waste_end,
        ) = await _get_garden_bin(street_name, http)

        collections: list[Collection] = []
        food_start = min(refuse_start, recycling_start, glass_start)
        for index in range(56):
            collection_date = (
                food_start + timedelta(days=7 * index + food_offset_day)
            ).date()
            collections.append(Collection(collection_date, "Food Waste Bin"))

        for index in range(28):
            collection_date = (
                garden_start + timedelta(days=14 * index + garden_offset_day)
            )
            if no_garden_waste_start <= collection_date <= no_garden_waste_end:
                continue
            collections.append(
                Collection(collection_date.date(), "Brown Garden Waste Bin")
            )

        for bin_start, bin_type in (
            (refuse_start, "Grey Bin"),
            (recycling_start, "Green Bin"),
            (glass_start, "Glass Box"),
        ):
            for index in range(28):
                collection_date = (
                    bin_start + timedelta(days=14 * index + three_offset_days)
                ).date()
                collections.append(Collection(collection_date, bin_type))

        return collections


SCRAPER = CityOfEdinburgh()
