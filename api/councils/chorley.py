"""Chorley: submit a postcode and selected UPRN through its multi-step bin collection form."""

from __future__ import annotations

from datetime import datetime

from bs4 import BeautifulSoup, Tag

from api.councils._base import (
    Address,
    Collection,
    Http,
    Meta,
    Scraper,
    UpstreamError,
    soup,
)

_FORM_URL = "https://forms.chorleysouthribble.gov.uk/xfp/form/71"
_FIELD_PREFIX = "qc576c657112a8277ba6f954ebc0490c946168363"
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


def _token(page: BeautifulSoup) -> str:
    node = page.find("input", {"name": "__token"})
    if not isinstance(node, Tag):
        raise UpstreamError("Chorley's form page has no token")
    value = node.get("value")
    if not isinstance(value, str):
        raise UpstreamError("Chorley's form page has an invalid token")
    return value


class Chorley(Scraper):
    meta = Meta(
        title="Chorley Council",
        url="https://www.chorley.gov.uk",
        lads=("E07000118",),
        cases={
            "20 Leatherland Drive": {
                "postcode": "PR6 7YD",
                "uprn": "010091497098",
            },
        },
    )
    requires = frozenset({"postcode", "uprn"})
    headers = {"User-Agent": _USER_AGENT}

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        postcode = address.need("postcode")
        uprn = address.need("uprn").zfill(12)

        r = await http.get(_FORM_URL, params={"page": "198", "locale": "en_GB"})
        token = _token(soup(r.text))

        data = {
            "__token": token,
            "page": "198",
            "locale": "en_GB",
            f"{_FIELD_PREFIX}_0_0": postcode,
            "next": "Next",
        }
        r = await http.post(_FORM_URL, data=data)
        token = _token(soup(r.text))

        data = {
            "__token": token,
            "page": "198",
            "locale": "en_GB",
            f"{_FIELD_PREFIX}_0_0": postcode,
            f"{_FIELD_PREFIX}_1_0": uprn,
            "next": "Next",
        }
        r = await http.post(_FORM_URL, data=data)
        page = soup(r.text)

        collections = []
        for tr in page.find_all("tr")[1:]:
            cells = tr.find_all("td")
            if len(cells) < 2:
                continue

            service = cells[0].get_text(strip=True)
            date_text = cells[1].get_text(strip=True)
            waste_type = service.replace(" Collection Service", "")

            try:
                collection_date = datetime.strptime(date_text, "%d/%m/%y").date()
            except ValueError:
                continue

            collections.append(Collection(collection_date, waste_type))

        return collections


SCRAPER = Chorley()
