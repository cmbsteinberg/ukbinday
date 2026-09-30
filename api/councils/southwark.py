"""Southwark: looks up a property's UPRN and parses its bin collection dates."""

from __future__ import annotations

from dateutil import parser

from api.councils._base import Address, Collection, Http, Meta, Scraper, soup

_API_URL = "https://services.southwark.gov.uk/bins/lookup/"
_NAME_MAP = {
    "Refuse": "General Waste",
    "Communal Food": "Food Waste",
}


class Southwark(Scraper):
    meta = Meta(
        title="London Borough of Southwark",
        url="https://www.southwark.gov.uk/",
        lads=("E09000028",),
        cases={
            "Test_001": {"uprn": "200003455089"},
            "Test_002": {"uprn": "200003379615"},
        },
    )
    requires = frozenset({"uprn"})
    headers = {"user-agent": "Mozilla/5.0"}

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        uprn = address.need("uprn").zfill(12)
        response = await http.get(f"{_API_URL}{uprn}", timeout=10)
        page = soup(response.text)

        collections = []
        for block in page.find_all("div", class_="binProduct"):
            title_tag = block.select_one("p.h3:not(.hide-for-sr)")
            if not title_tag:
                continue

            bin_type = title_tag.get_text(strip=True)
            bin_type = bin_type.removesuffix(" Collection").strip()
            bin_type = _NAME_MAP.get(bin_type, bin_type)

            next_tag = block.find("p", string=lambda text: text and "Next collection:" in text)
            if not next_tag:
                continue

            date_text = next_tag.text.replace("Next collection:", "").strip()
            collections.append(Collection(parser.parse(date_text).date(), bin_type))

        return collections


SCRAPER = Southwark()
