"""Oxford: submit the UPRN and postcode to its form and parse the next collection dates."""

from __future__ import annotations

import re
from datetime import datetime

from api.councils._base import (
    Address,
    AddressNotFound,
    Collection,
    Http,
    Meta,
    Scraper,
    UpstreamError,
    soup,
)

_API_URL = "https://www.oxford.gov.uk/xfp/form/142"
_HEADERS = {"user-agent": "Mozilla/5.0"}
_COLLECTION_PATTERN = re.compile(r"^Your next (\w+) collections: (.*), (.*)")


class Oxford(Scraper):
    meta = Meta(
        title="Oxford City Council",
        url="https://oxford.gov.uk",
        lads=("E07000178",),
        cases={
            "Magdalen Road": {"uprn": "100120827594", "postcode": "OX4 1RB"},
            "Oliver Road (brown bin too)": {"uprn": "100120831804", "postcode": "OX4 2JH"},
        },
    )
    requires = frozenset({"uprn", "postcode"})
    headers = _HEADERS
    transport = __import__("api.councils._base", fromlist=["Transport"]).Transport.CURL_CFFI

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        landing_response = await http.get(_API_URL)
        token_input = soup(landing_response.text).find("input", {"name": "__token"})
        token = token_input.get("value") if token_input is not None else None
        if not token:
            raise UpstreamError("Could not parse CSRF token from Oxford's initial response")

        form_data = {
            "__token": token,
            "page": "12",
            "locale": "en_GB",
            "q6ad4e3bf432c83230a0347a6eea6c805c672efeb_0_0": address.need("postcode"),
            "q6ad4e3bf432c83230a0347a6eea6c805c672efeb_1_0": address.need("uprn"),
            "next": "Next",
        }
        collection_response = await http.post(_API_URL, data=form_data)
        collection_soup = soup(collection_response.text)
        paragraphs = collection_soup.select(
            "div.form__instructions div.editor p"
        )

        entries: list[Collection] = []
        for paragraph in paragraphs:
            matches = _COLLECTION_PATTERN.match(paragraph.get_text())
            if not matches:
                continue

            collection_type, first_date_string, second_date_string = matches.groups()
            try:
                try:
                    first_date = datetime.strptime(
                        first_date_string, "%A %d %B %Y"
                    ).date()
                except ValueError:
                    first_date = datetime.strptime(
                        first_date_string, "%A %d %b %Y"
                    ).date()

                try:
                    second_date = datetime.strptime(
                        second_date_string.strip(), "%A %d %B %Y"
                    ).date()
                except ValueError:
                    second_date = datetime.strptime(
                        second_date_string.strip(), "%A %d %b %Y"
                    ).date()
            except ValueError:
                continue

            bin_type = collection_type.capitalize()
            entries.append(Collection(first_date, bin_type))
            if second_date != first_date:
                entries.append(Collection(second_date, bin_type))

        if not entries:
            raise AddressNotFound(
                "Could not get collections for the given UPRN and postcode"
            )

        return entries


SCRAPER = Oxford()
