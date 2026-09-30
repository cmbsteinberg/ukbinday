"""Birmingham: look up collections by UPRN and postcode, falling back to the legacy form."""

from __future__ import annotations

from datetime import datetime, timedelta

from bs4 import Tag

from api.councils._base import (
    Address,
    AddressNotFound,
    Collection,
    Http,
    Meta,
    Scraper,
    Transport,
    UpstreamError,
    parse_date,
    soup,
)

_API_URL = "https://www.birmingham.gov.uk/info/50388/check_your_collection_day"
_LEGACY_API_URL = "https://www.birmingham.gov.uk/xfp/form/619"
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36",
}
_NOT_FOUND_TEXT = "Unfortunately we have been unable to find your rubbish collection schedule."


async def _legacy_api(address: Address, http: Http) -> list[Collection]:
    token_response = await http.get(_LEGACY_API_URL)
    page = soup(token_response.text)
    token_input = page.find("input", {"name": "__token"})
    if not isinstance(token_input, Tag) or not token_input.get("value"):
        raise UpstreamError("Could not parse CSRF Token from initial response")

    form_data = {
        "__token": token_input["value"],
        "page": "491",
        "locale": "en_GB",
        "q1f8ccce1d1e2f58649b4069712be6879a839233f_0_0": address.need("postcode"),
        "q1f8ccce1d1e2f58649b4069712be6879a839233f_1_0": address.need("uprn"),
        "next": "Next",
    }
    collection_response = await http.post(_LEGACY_API_URL, data=form_data)
    collection_page = soup(collection_response.text)
    table = collection_page.find("table", class_="data-table")
    if not isinstance(table, Tag) or not isinstance(table.tbody, Tag):
        raise UpstreamError("Could not find Birmingham's legacy collection schedule table")

    entries: list[Collection] = []
    for table_row in table.tbody.find_all("tr"):
        cells = table_row.find_all(["th", "td"])
        if len(cells) < 2:
            continue
        collection_type = cells[0].get_text().strip()
        collection_next = cells[1].get_text().strip()
        try:
            collection_date = datetime.strptime(collection_next, "%a %d/%m/%Y").date()
        except ValueError as exc:
            raise UpstreamError("Could not parse a date in Birmingham's legacy collection schedule") from exc
        entries.append(Collection(collection_date, collection_type))

    if not entries:
        raise AddressNotFound("Could not get collections for the given combination of UPRN and Postcode")
    return entries


class Birmingham(Scraper):
    meta = Meta(
        title="Birmingham City Council",
        url="https://birmingham.gov.uk",
        lads=("E08000025",),
        cases={
            "Cherry Tree Croft": {"uprn": "100070321799", "postcode": "B27 6TF"},
            "Ludgate Loft Apartments": {"uprn": "10033389698", "postcode": "B3 1DW"},
            "Victoria Road": {"uprn": "100070548572", "postcode": "B17 0AH"},
        },
    )
    requires = frozenset({"uprn", "postcode"})
    headers = _HEADERS
    transport = Transport.CURL_CFFI

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        response = await http.get(
            _API_URL,
            params={
                "postcode": address.need("postcode"),
                "uprn": address.need("uprn"),
                "next": "Next",
            },
            timeout=30,
        )
        page = soup(response.text)

        not_found = page.find("p", string=_NOT_FOUND_TEXT)
        if not_found:
            return await _legacy_api(address, http)

        table = page.find("table", class_="data-table")
        if not isinstance(table, Tag) or not isinstance(table.tbody, Tag):
            raise UpstreamError("Could not find Birmingham's collection schedule table")

        today = datetime.now()
        cutoff = (today - timedelta(days=1)).date()
        entries: list[Collection] = []

        for table_row in table.tbody.find_all("tr"):
            cells = table_row.find_all(["th", "td"])
            if len(cells) < 2:
                continue

            raw_date = cells[0].get_text().strip()
            collection_type = cells[1].get_text().strip()
            try:
                collection_date = parse_date(raw_date)
            except ValueError as exc:
                raise UpstreamError("Could not parse a date in Birmingham's collection schedule") from exc
            if collection_date < cutoff:
                continue
            entries.append(Collection(collection_date, collection_type))

        if not entries:
            raise AddressNotFound("Could not get collections for the given combination of UPRN and Postcode")
        return entries


SCRAPER = Birmingham()
