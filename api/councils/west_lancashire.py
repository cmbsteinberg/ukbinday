"""West Lancashire: postcode lookup, UPRN address selection, then an ASP.NET form post."""

from __future__ import annotations

import re
from datetime import datetime

from bs4 import Tag

from api.councils._base import (
    Address,
    AddressNotFound,
    Collection,
    Http,
    Meta,
    Scraper,
    UpstreamError,
    match_address,
    soup,
    text_of,
)

API_URL = "https://your.westlancs.gov.uk/yourwestlancs.aspx"
_COLLECTION_PATTERNS = (
    ("Refuse", r"Next refuse collection:\s*(\d{2}/\d{2}/\d{4})"),
    ("Recycling", r"Next recycling collection:\s*(\d{2}/\d{2}/\d{4})"),
    ("Garden Waste", r"Next garden waste collection:\s*(\d{2}/\d{2}/\d{4})"),
)


def _row_uprn(row: Tag) -> str | None:
    for cell in row.find_all("td"):
        value = cell.get_text(strip=True)
        if value.isdigit():
            return value
    return None


class WestLancashire(Scraper):
    meta = Meta(
        title="West Lancashire Council",
        url="https://westlancs.gov.uk",
        lads=("E07000127",),
        cases={
            "Test 1": {"postcode": "WN8 9QR", "uprn": "10012340497"},
            "Test 2": {"postcode": "WN8 9DA", "uprn": "10012357342"},
        },
    )
    requires = frozenset({"postcode"})

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        postcode = address.need("postcode").strip().replace(" ", "+").upper()
        url = f"{API_URL}?address={postcode}"

        r = await http.get(url)
        if "no properties found" in r.text.lower():
            raise AddressNotFound(f"No properties found for postcode {postcode}")

        page = soup(r.text)
        gridview = page.find("table", {"id": re.compile("GridView")})
        if not isinstance(gridview, Tag):
            raise AddressNotFound(f"No properties found for postcode {postcode}")

        rows = gridview.find_all("tr")
        selected_link: Tag | None = None

        if address.uprn is not None:
            for row in rows:
                for cell in row.find_all("td"):
                    if cell.get_text(strip=True) == address.uprn:
                        link = row.find("a")
                        if isinstance(link, Tag):
                            selected_link = link
                            break
                if selected_link is not None:
                    break
        else:
            candidates = [
                row for row in rows
                if isinstance(row.find("a"), Tag)
            ]
            selected_row = match_address(
                address,
                candidates,
                text=text_of,
                uprn=_row_uprn,
            )
            link = selected_row.find("a")
            if isinstance(link, Tag):
                selected_link = link

        if selected_link is None:
            raise AddressNotFound(
                f"No address found for postcode {postcode}"
                + (f" and UPRN {address.uprn}" if address.uprn else "")
            )

        onclick = selected_link.get("href", "")
        if not isinstance(onclick, str):
            onclick = ""
        match = re.search(
            r"__doPostBack\s*\(\s*'([^']+)'\s*,\s*'([^']+)'\s*\)",
            onclick,
        )
        if not match:
            raise UpstreamError(f"Could not parse address link: {onclick}")

        form_data = {
            "__EVENTTARGET": match.group(1),
            "__EVENTARGUMENT": match.group(2),
        }
        for field in ("__VIEWSTATE", "__VIEWSTATEGENERATOR", "__EVENTVALIDATION"):
            element = page.find("input", {"name": field})
            if isinstance(element, Tag):
                value = element.get("value", "")
                form_data[field] = value if isinstance(value, str) else ""

        r = await http.post(url, data=form_data)
        content = soup(r.text).get_text()
        collections: list[Collection] = []

        for waste_type, pattern in _COLLECTION_PATTERNS:
            date_match = re.search(pattern, content, re.IGNORECASE)
            if date_match:
                try:
                    day = datetime.strptime(date_match.group(1), "%d/%m/%Y").date()
                except ValueError:
                    continue
                collections.append(Collection(day, waste_type))
            elif waste_type == "Garden Waste" and "Not subscribed" in content:
                continue

        if not collections:
            raise UpstreamError("No collection dates found")
        return collections


SCRAPER = WestLancashire()
