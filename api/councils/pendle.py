"""Pendle: find a property by postcode, then query its map layer for collection dates."""

from __future__ import annotations

import logging
import re
from datetime import date, datetime, timedelta
from typing import Any

from api.councils._base import (
    Address,
    AddressNotFound,
    Collection,
    Http,
    InputError,
    Meta,
    Scraper,
    match_address,
)

_MAP_CONFIG_URL = "https://opus4.co.uk/api/v1/map-configs/{map_id}"
_ADDRESS_SEARCH_URL = "https://opus4.co.uk/api/v1/address-search"
_CLIENT = "pendle"
_CLIENT_ID = 5
_MAP_ID = 3606
_LANGUAGE = "en-GB"
_WEEKS_AHEAD = 12
_REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0"
}
_WEEKDAYS = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}
_LOGGER = logging.getLogger(__name__)


def _normalise(value: str | None) -> str:
    if value is None:
        return ""
    return re.sub(r"[^A-Za-z0-9]", "", value).upper()


def _parse_relative_date(value: str | None) -> date | None:
    if not value:
        return None

    today = date.today()
    text = value.strip().lower()

    match = re.search(r"\(in (\d+) days?\)", text)
    if match:
        return today + timedelta(days=int(match.group(1)))

    match = re.search(r"\bin (\d+) days?\b", text)
    if match:
        return today + timedelta(days=int(match.group(1)))

    match = re.search(
        r"\bin (\d+) weeks?\s+on\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
        text,
    )
    if match:
        weeks = int(match.group(1))
        target = _WEEKDAYS[match.group(2)]
        days_ahead = (target - today.weekday()) % 7
        return today + timedelta(days=days_ahead, weeks=weeks)

    match = re.search(r"\bin (\d+) weeks?\b", text)
    if match:
        return today + timedelta(weeks=int(match.group(1)))

    if text == "today":
        return today
    if text == "tomorrow":
        return today + timedelta(days=1)

    match = re.search(
        r"\bnext (monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
        text,
    )
    if match:
        target = _WEEKDAYS[match.group(1)]
        days_ahead = (target - today.weekday()) % 7
        if days_ahead == 0:
            days_ahead = 7
        return today + timedelta(days=days_ahead)

    return None


def _parse_start_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(value.strip(), "%d %B, %Y").date()
    except ValueError:
        return None


def _next_occurrence_from_anchor(
    start_date: date | None, frequency_weeks: int | None
) -> date | None:
    if start_date is None:
        return None

    if not frequency_weeks or frequency_weeks < 1:
        return start_date

    today = date.today()
    next_date = start_date
    while next_date < today:
        next_date += timedelta(weeks=frequency_weeks)
    return next_date


def _parse_weekday(value: str | None) -> int | None:
    if not value:
        return None
    return _WEEKDAYS.get(value.strip().lower())


def _resolve_next_collection_date(
    item: dict[str, Any], title: str, frequency_weeks: int | None
) -> date | None:
    expected_date = _next_occurrence_from_anchor(
        _parse_start_date(item.get("startDate")),
        frequency_weeks,
    )
    actual_date = _parse_relative_date(item.get("when"))
    weekday = _parse_weekday(item.get("day"))

    if actual_date is not None and weekday is not None and actual_date.weekday() != weekday:
        _LOGGER.warning(
            "Pendle parsed when mismatch for %s: parsed %s but council day is %s. "
            "Ignoring parsed date and falling back to schedule anchor.",
            title,
            actual_date.isoformat(),
            item.get("day"),
        )
        actual_date = None

    next_date = actual_date or expected_date
    if next_date is None:
        return None

    if actual_date is not None and expected_date is not None and actual_date != expected_date:
        _LOGGER.warning(
            "Pendle schedule override for %s: expected %s from startDate/frequency, "
            "but council when says %s. Using council date.",
            title,
            expected_date.isoformat(),
            actual_date.isoformat(),
        )

    if weekday is not None and next_date.weekday() != weekday:
        _LOGGER.warning(
            "Pendle weekday mismatch for %s: resolved %s but council day is %s.",
            title,
            next_date.isoformat(),
            item.get("day"),
        )

    return next_date


def _enabled(value: str | None) -> bool:
    return value is not None and value.strip().lower() in {"1", "true", "yes", "on"}


def _expand_optional_collections(title: str, garden_waste_bin: bool) -> list[str]:
    titles = [title]
    if garden_waste_bin and title.strip().lower() in {"blue collection", "brown collection"}:
        titles.append("Green Collection")
    return titles


def _expand_dates(first_date: date, frequency_weeks: int | None) -> list[date]:
    if not frequency_weeks or frequency_weeks < 1:
        return [first_date]

    dates = [first_date]
    next_date = first_date
    while True:
        next_date += timedelta(weeks=frequency_weeks)
        if (next_date - first_date).days > _WEEKS_AHEAD * 7:
            break
        dates.append(next_date)
    return dates


class Pendle(Scraper):
    meta = Meta(
        title="Pendle Borough Council",
        url="https://www.pendle.gov.uk/binday",
        lads=("E07000122",),
        cases={
            "Pendle Market Street": {
                "postcode": "BB9 7LJ",
                "house_number": "1",
                "street": "MARKET STREET",
                "address": "PENDLE LEISURE TRUST, 1, MARKET STREET, NELSON",
            }
        },
    )
    requires = frozenset()
    headers = _REQUEST_HEADERS

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        postcode = address.postcode
        house_street = (
            f"{address.house_number} {address.street}"
            if address.house_number and address.street
            else None
        )
        search_address = house_street or address.label
        if not postcode:
            raise InputError("postcode is needed to look up Pendle addresses")
        if not search_address:
            raise InputError("address is needed to pick the correct Pendle property")

        collection_zone = address.extra.get("collection_zone")
        if collection_zone:
            collection_zone = collection_zone.strip() or None
        garden_waste_bin = _enabled(address.extra.get("garden_waste_bin"))
        future_collection_dates = _enabled(address.extra.get("future_collection_dates"))

        response = await http.get(
            _MAP_CONFIG_URL.format(map_id=_MAP_ID),
            params={"c": _CLIENT_ID, "l": _LANGUAGE},
            timeout=30,
        )
        map_config = response.json()

        response = await http.get(
            _ADDRESS_SEARCH_URL,
            params={
                "address": search_address,
                "postcode": postcode,
                "page": 1,
                "size": 25,
                "client": _CLIENT,
            },
            timeout=30,
        )
        payload = response.json()
        addresses = ((payload.get("Results") or {}).get("Addresses") or {}).get("Address")
        if addresses is None:
            raise AddressNotFound(f"Pendle did not return any matching addresses for {postcode}")
        if isinstance(addresses, dict):
            candidates = [addresses]
        else:
            candidates = list(addresses)

        selected_address = match_address(
            address,
            candidates,
            text=lambda item: str(item.get("FullAddress") or ""),
            uprn=lambda item: item.get("UPRN", item.get("uprn")),
        )

        layer_groups = map_config.get("legend", {}).get("layerGroups", [])
        layers = layer_groups[0].get("layers", []) if layer_groups else []
        layer_id = layers[0].get("id") if layers else None
        wms_url = map_config.get("doubleClick", {}).get("url")

        if not layer_id or not wms_url:
            raise InputError("Pendle map configuration is missing the query layer details")

        collections: list[dict[str, Any]] = []
        for buffer_size in (500, 1000, 1500):
            response = await http.get(
                wms_url,
                params={
                    "service": "WMS",
                    "version": "1.1.1",
                    "request": "GetFeatureInfo",
                    "layers": "none",
                    "styles": "",
                    "srs": "EPSG:27700",
                    "bbox": (
                        f"{float(selected_address['X']) - buffer_size},"
                        f"{float(selected_address['Y']) - buffer_size},"
                        f"{float(selected_address['X']) + buffer_size},"
                        f"{float(selected_address['Y']) + buffer_size}"
                    ),
                    "width": 256,
                    "height": 256,
                    "query_layers": layer_id,
                    "info_format": "application/json",
                    "x": 128,
                    "y": 128,
                },
                timeout=30,
            )
            data = response.json()
            if data:
                collections = list(data)
                break

        locations = sorted(
            {
                str(item.get("location")).strip()
                for item in collections
                if item.get("location") is not None and str(item.get("location")).strip()
            }
        )
        if len(locations) > 1:
            if collection_zone:
                selected = [
                    item
                    for item in collections
                    if str(item.get("location", "")).strip() == collection_zone
                ]
                if selected:
                    collections = selected
                else:
                    raise InputError(
                        "Pendle did not return that collection zone for the selected address"
                    )
            else:
                raise AddressNotFound(
                    "Multiple Pendle collection zones were returned for this address",
                    locations,
                )

        if not collections:
            raise AddressNotFound(f"No Pendle collections found for {address.label or search_address}")

        entries: list[Collection] = []
        for item in collections:
            title = item.get("title", "Collection")
            frequency_weeks = item.get("frequency")
            next_date = _resolve_next_collection_date(item, title, frequency_weeks)
            if next_date is None:
                continue

            collection_dates = (
                _expand_dates(next_date, frequency_weeks)
                if future_collection_dates
                else [next_date]
            )
            for collection_date in collection_dates:
                for expanded_title in _expand_optional_collections(title, garden_waste_bin):
                    entries.append(Collection(collection_date, expanded_title))

        return entries


SCRAPER = Pendle()
