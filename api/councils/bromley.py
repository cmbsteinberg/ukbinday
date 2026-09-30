"""Bromley: submit a postcode, select the matching property, then poll for its waste schedule."""

from __future__ import annotations

import asyncio
import re
from datetime import date

from api.councils._base import (
    Address,
    AddressNotFound,
    Collection,
    Http,
    Meta,
    Scraper,
    UpstreamError,
    match_address,
    parse_date,
    soup,
    text_of,
)

URL = "https://recyclingservices.bromley.gov.uk"
BASE_URL = f"{URL}/waste"
MAX_POLLS = 10
POLL_INTERVAL_S = 2


def _parse_schedule(html: str) -> list[Collection]:
    entries: list[Collection] = []

    for service in soup(html).find_all("div", class_="waste-service-grid"):
        heading = service.find("h3", class_="waste-service-name")
        if heading is None:
            continue
        service_name = heading.get_text(strip=True)

        for row in service.find_all("div", class_="govuk-summary-list__row"):
            dt = row.find("dt", string="Next collection")
            if dt is None:
                continue
            dd = dt.find_next_sibling()
            if dd is None:
                continue

            text = dd.get_text(strip=True)
            date_part = text.split(",", 1)[-1].strip() if "," in text else text
            match = re.match(r"(\d+\w*\s+\w+)", date_part)
            if match is None:
                continue
            try:
                collection_date: date = parse_date(match.group(1))
            except ValueError:
                continue

            entries.append(Collection(collection_date, service_name))

    return entries


class Bromley(Scraper):
    meta = Meta(
        title="Bromley Borough Council",
        url=URL,
        lads=("E09000006",),
        cases={
            "Test_001": {
                "postcode": "BR1 3PU",
                "house_number": "17",
                "street": "College Road",
            },
        },
    )
    requires = frozenset({"postcode"})
    headers = {"User-Agent": "Mozilla/5.0"}

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        r = await http.post(
            BASE_URL,
            data={"postcode": address.need("postcode")},
            timeout=30.0,
        )
        page = soup(r.text)
        selector = page.find("select", attrs={"name": "address"})
        if selector is None:
            raise AddressNotFound(f"No address selector found for postcode {address.postcode}")

        options = [
            option
            for option in selector.find_all("option")
            if option.get("value", "").strip()
        ]
        option = match_address(address, options, text=text_of)
        property_id = option["value"].strip()

        await http.post(
            BASE_URL,
            data={"address": property_id, "go": "Go"},
            timeout=30.0,
            check=False,
        )

        url = f"{BASE_URL}/{property_id}"
        for _ in range(MAX_POLLS):
            await asyncio.sleep(POLL_INTERVAL_S)
            r = await http.get(url, timeout=30.0)
            entries = _parse_schedule(r.text)
            if entries:
                return entries

        raise UpstreamError(
            f"Schedule not ready after {MAX_POLLS * POLL_INTERVAL_S}s for property {property_id}"
        )


SCRAPER = Bromley()
