"""Leicester: query Biffa's admin-ajax endpoint by UPRN for collection dates."""

from __future__ import annotations

from datetime import datetime

from api.councils._base import Address, Collection, Http, Meta, Scraper

_URI = "https://biffaleicester.co.uk/wp-admin/admin-ajax.php"
_HEADERS = {
    "Origin": "https://biffaleicester.co.uk",
    "Referer": "https://biffaleicester.co.uk/services/waste-collection-days/",
    "User-Agent": "Mozilla/5.0",
}


class Leicester(Scraper):
    meta = Meta(
        title="Leicester",
        url="https://biffaleicester.co.uk",
        lads=("E06000016",),
        cases={},
    )
    requires = frozenset({"uprn"})

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        r = await http.post(
            _URI,
            headers=_HEADERS,
            data={
                "action": "get_details_api",
                "uprn": address.need("uprn").zfill(12),
            },
        )

        bin_collection = r.json()
        collections = []
        for collection in bin_collection["anyType"]:
            collections.append(
                Collection(
                    datetime.strptime(collection["ServiceDueDate"], "%d/%m/%y").date(),
                    collection["ServiceModeDesc"],
                )
            )
        return collections


SCRAPER = Leicester()
