"""Monmouthshire: look up waste collections by UPRN on the council's local information page."""

from __future__ import annotations

from api.councils._base import (
    Address,
    Collection,
    Http,
    InputError,
    Meta,
    Scraper,
    parse_date,
    soup,
)

_API_URL = "https://maps.monmouthshire.gov.uk/localinfo.aspx"
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.5",
}


class Monmouthshire(Scraper):
    meta = Meta(
        title="Monmouthshire Council",
        url="https://www.monmouthshire.gov.uk",
        lads=("W06000021",),
        cases={
            "200000952833": {"uprn": "200000952833"},
            "10033354474": {"uprn": "10033354474"},
            "10033351693": {"uprn": "10033351693"},
        },
    )
    requires = frozenset({"uprn"})
    headers = _HEADERS

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        uprn = address.need("uprn")
        r = await http.get(
            _API_URL,
            params={"action": "SetAddress", "UniqueId": uprn},
            timeout=30,
        )

        page = soup(r.text)
        uprn_check = page.find("b", string="Unique Property Reference Number (UPRN):")

        if not uprn_check or not uprn_check.next_sibling:
            raise InputError(
                f"UPRN {uprn} is invalid or outside the Monmouthshire Council area."
            )

        if str(uprn_check.next_sibling).strip() != uprn:
            raise InputError(f"UPRN {uprn} does not match the UPRN provided.")

        collections = []
        waste_div = page.find("div", attrs={"aria-label": "Waste Collections"})

        if waste_div:
            for waste_block in waste_div.find_all("div", class_="waste"):
                waste_h4 = waste_block.find("h4")
                collection_strong = waste_block.find("strong")

                if waste_h4 and collection_strong:
                    waste_type = " ".join(waste_h4.get_text().split())
                    waste_type = waste_type.replace(" (pay to use service)", "")
                    collection_date_text = collection_strong.get_text(strip=True)

                    try:
                        collection_date = parse_date(collection_date_text)
                    except ValueError:
                        continue

                    collections.append(Collection(collection_date, waste_type))

        if not collections:
            raise InputError("No collection dates found in response.")

        return collections


SCRAPER = Monmouthshire()
