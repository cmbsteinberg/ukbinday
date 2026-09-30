"""South Ribble: a postcode and selected UPRN are submitted through a multi-step form."""

from __future__ import annotations

import datetime
import re

from api.councils._base import (
    Address,
    Collection,
    Http,
    Meta,
    Scraper,
    UpstreamError,
    soup,
)

_FORM_URL = "https://forms.chorleysouthribble.gov.uk/xfp/form/70"
_FIELD_PREFIX = "qc576c657112a8277ba6f954ebc0490c946168363"
_PAGE = "196"


def _token(page: object) -> str:
    """Read the form token, raising an upstream error if the form is unavailable."""
    node = page.find("input", {"name": "__token"})  # type: ignore[attr-defined]
    if node is None or not node.get("value"):
        raise UpstreamError("South Ribble form has no token")
    return node["value"]


class SouthRibble(Scraper):
    meta = Meta(
        title="South Ribble Borough Council",
        url="https://www.southribble.gov.uk",
        lads=("E07000126",),
        cases={
            "South Ribble Borough Council, Civic Centre, W Paddock, Leyland PR25 1DH": {
                "postcode": "PR25 1DH",
                "uprn": "100012755948",
            },
        },
    )
    requires = frozenset({"postcode", "uprn"})
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
    }

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        postcode = address.need("postcode")
        uprn = address.need("uprn")

        r = await http.get(_FORM_URL, params={"page": _PAGE, "locale": "en_GB"})
        token = _token(soup(r.text))

        data = {
            "__token": token,
            "page": _PAGE,
            "locale": "en_GB",
            f"{_FIELD_PREFIX}_0_0": postcode,
            "next": "Next",
        }
        r = await http.post(_FORM_URL, data=data)
        token = _token(soup(r.text))

        data = {
            "__token": token,
            "page": _PAGE,
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
            waste_type = re.sub(r" Collection(?: Service)?$", "", service).strip()

            try:
                collection_date = datetime.datetime.strptime(date_text, "%d/%m/%y").date()
            except ValueError:
                continue

            collections.append(Collection(collection_date, waste_type))

        return collections


SCRAPER = SouthRibble()
