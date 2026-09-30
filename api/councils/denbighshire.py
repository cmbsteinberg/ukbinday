"""Denbighshire: fetches a CSRF token, then requests the UPRN's collection calendar."""

from __future__ import annotations

from datetime import datetime

from api.councils._base import Address, Collection, Http, Meta, Scraper

_API_URL = "https://refusecalendarapi.denbighshire.gov.uk/Calendar/{uprn}"
_CSRF_TOKEN_URL = "https://refusecalendarapi.denbighshire.gov.uk/Csrf/token"


class Denbighshire(Scraper):
    meta = Meta(
        title="Denbighshire County Council",
        url="https://www.denbighshire.gov.uk/",
        lads=("W06000004",),
        cases={
            "10003928409": {"uprn": "10003928409"},
            "100100183412": {"uprn": "100100183412"},
            "10003928445": {"uprn": "10003928445"},
        },
    )
    requires = frozenset({"uprn"})

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        token_response = await http.get(_CSRF_TOKEN_URL)
        token = token_response.json()["token"]

        response = await http.get(
            _API_URL.format(uprn=address.need("uprn")),
            headers={"X-CSRF-TOKEN": token},
        )

        collections = []
        for key, value in response.json().items():
            if not key.endswith("Date") or not value:
                continue

            bin_types = [key.replace("Date", "").lower()]
            if bin_types[0] == "recycling":
                bin_types.append("food")
            day = datetime.strptime(value, "%d/%m/%Y").date()

            for bin_type in bin_types:
                collections.append(Collection(day, bin_type))

        return collections


SCRAPER = Denbighshire()
