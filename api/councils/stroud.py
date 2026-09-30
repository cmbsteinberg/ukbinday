"""Stroud: bin collections looked up from the council's my-house page by postcode and UPRN."""

from __future__ import annotations

import re
from datetime import date, datetime

from bs4 import Tag

from api.councils._base import (
    Address,
    AddressNotFound,
    Collection,
    Http,
    Meta,
    Scraper,
    every,
    next_weekday,
    weekday_number,
)

_API_URL = "https://www.stroud.gov.uk/my-house"
_DATE_REGEX = re.compile(r"(\w+day) (\d{1,2}) (\w+) (\d{4})")
_EVERY_REGEX = re.compile(r"every (\w+)", re.IGNORECASE)
_WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


def _make_bin_type_string(bin_type: str) -> str:
    return (
        bin_type.lower()
        .replace("next", "")
        .replace("collection date", "")
        .replace("collection", "")
        .strip()
        .capitalize()
    )


def _parse_date_in_title(bin_type: str) -> Collection:
    match = _DATE_REGEX.match(bin_type)
    if not match:
        raise ValueError(f"Could not parse bin type: {bin_type}")

    day = datetime.strptime(
        f"{match.group(4)}-{match.group(3)}-{match.group(2)}", "%Y-%B-%d"
    ).date()
    bin_type = bin_type.replace(match.group(0), "").strip()
    return Collection(day, bin_type)


def _parse_every(date_string: str, bin_type: str) -> list[Collection]:
    match = _EVERY_REGEX.match(date_string)
    if not match:
        raise ValueError(
            f"Could not parse bin type: {bin_type} with date string: {date_string}"
        )

    weekday = match.group(1).lower()
    if weekday not in _WEEKDAYS:
        raise ValueError(f"Could not find weekday: {weekday} in next 7 days")

    start = next_weekday(weekday_number(weekday), after=date.today())
    return [Collection(day, bin_type) for day in every(start, days=7, count=10)]


def _parse_entry(date_string: str, bin_type: str) -> list[Collection]:
    if date_string.lower().startswith("every"):
        try:
            return _parse_every(date_string, bin_type)
        except ValueError:
            return []

    try:
        day = datetime.strptime(date_string, "%A %d %B %Y").date()
        return [Collection(day, bin_type)]
    except ValueError:
        try:
            return [_parse_date_in_title(bin_type)]
        except ValueError:
            return []


class Stroud(Scraper):
    meta = Meta(
        title="Stroud District Council",
        url="https://stroud.gov.uk",
        lads=("E07000082",),
        cases={
            "GL6+9BW 100120517945": {
                "postcode": "GL6 9BW",
                "uprn": "100120517945",
            },
        },
    )
    requires = frozenset({"postcode", "uprn"})

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        r = await http.get(
            _API_URL,
            params={
                "postcode": address.need("postcode"),
                "uprn": address.need("uprn"),
            },
        )

        page = __import__("api.councils._base", fromlist=["soup"]).soup(r.text)
        rubbish_panels = page.select("section.panel-rubbish")
        if not rubbish_panels:
            raise AddressNotFound(
                "No data found for this postcode and uprn (could not find panel-rubbish)"
            )

        items = rubbish_panels[0].select("li")
        if not items:
            raise AddressNotFound(
                "No data found for this postcode and uprn (could not find any collection entries)"
            )

        collections: list[Collection] = []
        for item in items:
            bin_type_tag = item.find("h3")
            if not isinstance(bin_type_tag, Tag):
                strongs = item.select("strong")
                if len(strongs) < 2:
                    continue
                collections.extend(
                    _parse_entry(
                        strongs[1].get_text(),
                        _make_bin_type_string(strongs[0].get_text()),
                    )
                )
                continue

            bin_type = _make_bin_type_string(bin_type_tag.get_text())
            date_string_tag = item.find("p")
            if not isinstance(date_string_tag, Tag):
                try:
                    collections.append(_parse_date_in_title(bin_type))
                except ValueError:
                    continue
                continue

            collections.extend(_parse_entry(date_string_tag.get_text(), bin_type))

        return collections


SCRAPER = Stroud()
