"""Lewisham: resolve an address to a UPRN, then submit it to the bin collection form."""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

from bs4 import NavigableString, Tag

from api.councils._base import (
    Address,
    Collection,
    Http,
    InputError,
    Meta,
    Scraper,
    UpstreamError,
    every,
    find_tag,
    match_address,
    next_weekday,
    soup,
    weekday_number,
)

_BASE_URL = "https://lewisham.gov.uk"
_ADDRESS_SEARCH_URL = "https://lewisham.gov.uk/api/AddressFinder"
_COLLECTION_PAGE_URL = "https://lewisham.gov.uk/myservices/recycling-and-rubbish/your-bins/collection"
_DATE_REGEX = re.compile(r"(\d{2}/\d{2}/\d{4})")
_DAY_REGEX = re.compile("monday|tuesday|wednesday|thursday|friday|saturday|sunday", re.IGNORECASE)
_ID_SEPARATOR = "-----------------------------{rand_id}"
_PAYLOAD_SECTION_TEMPLATE = (
    _ID_SEPARATOR
    + """\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n"""
)


def _calculate_collections(
    waste_type: str | None,
    frequency: str | None,
    week_day: int | None,
    collection_date: date | None,
) -> list[Collection]:
    if waste_type is None:
        raise UpstreamError("Lewisham collection page: waste type not provided")
    if frequency not in ("WEEKLY", "FORTNIGHTLY"):
        raise UpstreamError(f"Lewisham collection page: no frequency for {waste_type!r}")
    if week_day is None:
        raise UpstreamError(f"Lewisham collection page: no week day for {waste_type!r}")
    if frequency == "FORTNIGHTLY" and collection_date is None:
        raise UpstreamError(f"Lewisham collection page: no date for {waste_type!r}")

    if collection_date is None:
        collection_date = next_weekday(week_day)

    fortnightly = frequency == "FORTNIGHTLY"
    days = every(collection_date, days=14 if fortnightly else 7, count=5 if fortnightly else 10)
    return [Collection(day, waste_type) for day in days]


class Lewisham(Scraper):
    meta = Meta(
        title="London Borough of Lewisham",
        url="https://lewisham.gov.uk",
        lads=("E09000023",),
        cases={
            "houseNumber": {"postcode": "SE4 1LR", "house_number": "4"},
            "houseName": {"postcode": "SE23 3TE", "house_number": "The Haven"},
            "houseUprn": {"uprn": "10070495030"},
        },
    )
    requires = frozenset()
    headers = {"User-Agent": "Mozilla/5.0"}

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        uprn: str | int | None = address.uprn
        if uprn is None:
            if address.postcode is None or address.first_line is None:
                raise InputError("Lewisham needs a UPRN or a postcode and address")

            response = await http.post(
                _ADDRESS_SEARCH_URL,
                params={"postcodeOrStreet": address.postcode},
            )
            candidates: list[dict[str, Any]] = response.json()
            selected = match_address(
                address,
                candidates,
                text=lambda candidate: str(candidate["Title"]),
                uprn=lambda candidate: candidate["Uprn"],
            )
            uprn = selected["Uprn"]

        response = await http.get(_COLLECTION_PAGE_URL)
        page = soup(response.text)
        form_div = find_tag(page, "div", {"class": "address-finder"}, what="Lewisham collection page has no address form")

        form = form_div.find_parent("form")
        if not isinstance(form, Tag):
            raise UpstreamError("Lewisham collection page has no address form")

        action = form.get("action")
        if not action:
            raise UpstreamError("Lewisham collection form has no action")
        if action.startswith("/"):
            action = _BASE_URL + action

        rand_id = datetime.now().strftime("%Y%m%d%H%M%S%f%f%H%m")
        payload = ""
        for input_element in form.find_all("input"):
            name = input_element.get("name")
            value = input_element.get("value")
            if name:
                if name.endswith("Value"):
                    value = uprn
                payload += _PAYLOAD_SECTION_TEMPLATE.format(
                    rand_id=rand_id,
                    name=name,
                    value=value,
                )
        payload += _ID_SEPARATOR.format(rand_id=rand_id) + "--\r\n"

        response = await http.post(
            action,
            content=payload,
            headers={
                "Content-Type": f"multipart/form-data; boundary=---------------------------{rand_id}",
                "Accept": "*/*",
                "X-Requested-With": "XMLHttpRequest",
            },
        )

        collection_url = response.text.split("='")[-1].split("';")[0]
        if not collection_url:
            raise UpstreamError("Lewisham response has no collection URL")
        if collection_url.startswith("/"):
            collection_url = _BASE_URL + collection_url

        response = await http.get(collection_url)
        page = soup(response.text)
        heading = page.find("h2", string="When your bins are collected:")
        if not isinstance(heading, Tag) or heading.parent is None:
            raise UpstreamError("Lewisham collection page has no collection heading")

        entries: list[Collection] = []
        waste_type: str | None = None
        frequency: str | None = None
        week_day: int | None = None
        collection_date: date | None = None

        for sibling in heading.parent.contents:
            if isinstance(sibling, Tag) and sibling.name == "strong":
                if waste_type is not None:
                    entries.extend(
                        _calculate_collections(
                            waste_type, frequency, week_day, collection_date
                        )
                    )
                    waste_type = None
                    frequency = None
                    week_day = None
                    collection_date = None
                waste_type = sibling.get_text().strip()

            if isinstance(sibling, Tag) and sibling.name == "span":
                frequency = sibling.get_text()

            if isinstance(sibling, NavigableString):
                text = str(sibling)
                if day_match := _DAY_REGEX.search(text):
                    week_day = weekday_number(day_match.group())
                if result := _DATE_REGEX.search(text):
                    collection_date = datetime.strptime(
                        result.group(1), "%d/%m/%Y"
                    ).date()

        entries.extend(
            _calculate_collections(waste_type, frequency, week_day, collection_date)
        )

        return entries


SCRAPER = Lewisham()
