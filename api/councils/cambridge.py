"""Cambridge: search the waste calendar by postcode, select the house number, then fetch its collections."""

from __future__ import annotations

from datetime import datetime

from api.councils._base import Address, Collection, Http, Meta, Scraper, match_address

_API_URLS = {
    "address_search": "https://servicelayer3c.azure-api.net/wastecalendar/address/search/",
    "collection": "https://servicelayer3c.azure-api.net/wastecalendar/collection/search/{}/",
}


class Cambridge(Scraper):
    meta = Meta(
        title="Cambridge City Council (Deprecated)",
        url="https://cambridge.gov.uk",
        lads=("E07000008",),
        cases={
            "houseNumber": {"postcode": "CB13JD", "house_number": "37"},
            "houseName": {"postcode": "cb215hd", "house_number": "ROSEMARY HOUSE"},
        },
    )
    requires = frozenset({"postcode", "house_number"})

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        r = await http.get(
            _API_URLS["address_search"],
            params={"postCode": address.need("postcode")},
        )
        addresses = r.json()
        candidate = match_address(
            address,
            addresses,
            text=lambda item: item["houseNumber"],
        )

        r = await http.get(_API_URLS["collection"].format(candidate["id"]))
        collections = r.json()["collections"]

        entries = []
        for collection in collections:
            for round_type in collection["roundTypes"]:
                entries.append(
                    Collection(
                        date=datetime.strptime(
                            collection["date"], "%Y-%m-%dT%H:%M:%SZ"
                        ).date(),
                        type=round_type.title(),
                    )
                )

        return entries


SCRAPER = Cambridge()
