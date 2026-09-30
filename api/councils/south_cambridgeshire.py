"""South Cambridgeshire: postcode search followed by a collection lookup for the matched house number."""

from __future__ import annotations

from datetime import datetime

from api.councils._base import (
    Address,
    AddressNotFound,
    Collection,
    Http,
    Meta,
    Scraper,
    UpstreamError,
    match_address,
)

_API_URLS = {
    "address_search": "https://servicelayer3c.azure-api.net/wastecalendar/address/search/",
    "collection": "https://servicelayer3c.azure-api.net/wastecalendar/collection/search/{}/",
}
_ROUNDS = {
    "DOMESTIC": "Black Bin",
    "RECYCLE": "Blue Bin",
    "ORGANIC": "Green Bin",
}


class SouthCambridgeshire(Scraper):
    meta = Meta(
        title="South Cambridgeshire District Council (Deprecated)",
        url="https://scambs.gov.uk",
        lads=("E07000012",),
        cases={
            "houseNumber": {"postcode": "CB23 6GZ", "house_number": "53"},
            "houseName": {"postcode": "CB22 5HT", "house_number": "Rectory Farm Cottage"},
        },
    )
    requires = frozenset({"postcode", "house_number"})

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        r = await http.get(
            _API_URLS["address_search"],
            params={"postCode": address.need("postcode")},
            check=False,
        )
        if r.status_code == 400:
            raise AddressNotFound(f"South Cambridgeshire has no results for postcode {address.postcode}")
        if r.status_code >= 400:
            raise UpstreamError(f"HTTP {r.status_code} from {r.url}")

        addresses = r.json()
        matched = match_address(
            address,
            addresses,
            text=lambda candidate: candidate["houseNumber"],
            uprn=lambda candidate: candidate.get("uprn"),
        )

        r = await http.get(_API_URLS["collection"].format(matched["id"]))
        collections = r.json()["collections"]

        entries = []
        for collection in collections:
            for round_type in collection["roundTypes"]:
                entries.append(
                    Collection(
                        date=datetime.strptime(collection["date"], "%Y-%m-%dT%H:%M:%SZ").date(),
                        type=_ROUNDS.get(round_type, round_type.title()),
                    )
                )
        return entries


SCRAPER = SouthCambridgeshire()
