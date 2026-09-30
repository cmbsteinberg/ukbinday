"""Shetland: search the council directory by postcode, then read collection weekdays from the matching record."""

from __future__ import annotations

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
    next_weekday,
    soup,
    text_of,
)

_SEARCH_URL = "https://www.shetland.gov.uk/directory/search"
_BASE_URL = "https://www.shetland.gov.uk"
_DAYS_OF_WEEK = frozenset(
    ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
)
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/138.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9",
}


class ShetlandIslands(Scraper):
    meta = Meta(
        title="Shetland Islands",
        url="https://www.shetland.gov.uk",
        lads=("S12000027",),
        cases={},
    )
    requires = frozenset({"postcode"})
    headers = _HEADERS

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        postcode = address.need("postcode")
        response = await http.get(
            _SEARCH_URL,
            params={"directoryID": "12", "keywords": postcode},
        )

        page = soup(response.text)
        result_list = page.find("ul", class_="list--record")
        if not isinstance(result_list, Tag):
            raise AddressNotFound(
                f"No collection records found for postcode {postcode}. "
                "Check the postcode is within the Shetland Islands."
            )

        record_links: list[tuple[str, str]] = []
        for item in result_list.find_all("li"):
            link = item.find("a", href=True)
            if isinstance(link, Tag):
                href = link.get("href")
                if isinstance(href, str):
                    record_links.append((href, text_of(link)))

        if not record_links:
            raise AddressNotFound(f"No collection records found for postcode {postcode}.")

        selected_link = record_links[0]
        if len(record_links) > 1 and (address.house_number or address.street or address.label):
            try:
                selected_link = match_address(
                    address,
                    record_links,
                    text=lambda record: record[1],
                )
            except AddressNotFound:
                # The directory's records can be area-wide rather than property-specific.
                pass

        response = await http.get(f"{_BASE_URL}{selected_link[0]}")
        record_page = soup(response.text)
        definition_list = record_page.find("dl")
        if not isinstance(definition_list, Tag):
            raise UpstreamError("Could not parse collection data from the record page.")

        collections: list[Collection] = []
        for term, description in zip(
            definition_list.find_all("dt"),
            definition_list.find_all("dd"), strict=False,
        ):
            label = text_of(term)
            if "Collection Day" not in label:
                continue

            day_name = text_of(description)
            if day_name in _DAYS_OF_WEEK:
                bin_type = label.replace(" Day", "").strip()
                collections.append(Collection(next_weekday(day_name), bin_type))

        if not collections:
            raise AddressNotFound(f"No collection days found for {selected_link[1]}.")

        return collections


SCRAPER = ShetlandIslands()
