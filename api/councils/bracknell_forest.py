"""Bracknell Forest: search addresses by postcode, then look up collections by address ID."""

from __future__ import annotations

import json

from dateutil import parser

from api.councils._base import (
    Address,
    Collection,
    Http,
    Meta,
    Scraper,
    match_address,
)

_URL = "https://selfservice.mybfc.bracknell-forest.gov.uk/w/webpage/waste-collection-days"
_PARAMS = {
    "webpage_subpage_id": "PAG0000570FEFFB1",
    "webpage_token": "390170046582b0e3d7ca68ef1d6b4829ccff0b1ae9c531047219c6f9b5295738",
    "widget_action": "handle_event",
}
_DATA = {
    "action_cell_id": "PCL0003988FEFFB1",
    "action_page_id": "PAG0000570FEFFB1",
}
_HEADERS = {
    "Accept": "application/json",
    "X-Requested-With": "XMLHttpRequest",
}


class BracknellForest(Scraper):
    meta = Meta(
        title="Bracknell Forest Council",
        url="https://selfservice.mybfc.bracknell-forest.gov.uk",
        lads=("E06000036",),
        cases={
            "44 Kennel Lane": {"house_number": "44", "postcode": "RG42 2HB"},
            "28 Kennel Lane": {"house_number": "28", "postcode": "RG42 2HB"},
            "32 Ashbourne": {"house_number": "32", "postcode": "RG12 8SG"},
        },
    )
    requires = frozenset({"postcode", "house_number"})
    headers = _HEADERS

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        address_lookup = await http.post(
            _URL,
            params=_PARAMS,
            data={
                "code_action": "find_addresses",
                "code_params": json.dumps({"search": address.need("postcode")}),
            }
            | _DATA,
            follow_redirects=True,
        )
        addresses = address_lookup.json()["response"]["addresses"]["items"]
        selected = match_address(
            address,
            addresses,
            text=lambda candidate: candidate["Description"],
        )

        collection_lookup = await http.post(
            _URL,
            params=_PARAMS,
            data={
                "code_action": "find_rounds",
                "code_params": json.dumps({"addressId": selected["Id"]}),
            }
            | _DATA,
            follow_redirects=True,
        )
        collections = collection_lookup.json()["response"]["collections"]
        entries = []
        for collection_entry in collections:
            try:
                coll_day = parser.parse(collection_entry["firstDate"]["date"]).date()
            except (KeyError, TypeError):
                continue
            entries.append(Collection(coll_day, collection_entry["round"]))
        return entries


SCRAPER = BracknellForest()
