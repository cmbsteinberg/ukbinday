"""Breckland: JSON-RPC lookup by UPRN, or postcode search followed by property matching."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from api.councils._base import (
    Address,
    AddressNotFound,
    Collection,
    Http,
    InputError,
    Meta,
    Scraper,
    match_address,
)

_API_URL = "https://www.breckland.gov.uk/apiserver/ajaxlibrary"
_HEADERS = {"referer": "https://www.breckland.gov.uk/mybreckland"}


class Breckland(Scraper):
    meta = Meta(
        title="Breckland Council",
        url="https://www.breckland.gov.uk/mybreckland",
        lads=("E07000143",),
        cases={
            "test1": {"postcode": "IP22 2LJ", "street": "glen travis"},
            "test2": {"uprn": "10011977093"},
        },
    )
    requires = frozenset()
    headers = _HEADERS

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        uprn: Any = address.uprn
        if uprn is None:
            if address.postcode is None or address.first_line is None:
                raise InputError("Specify a UPRN or a postcode and address")

            search = await http.post(
                _API_URL,
                json={
                    "jsonrpc": "2.0",
                    "id": "",
                    "method": "Breckland.Whitespace.JointWasteAPI.GetSiteIDsByPostcode",
                    "params": {"postcode": address.postcode, "environment": "live"},
                },
            )
            candidates = search.json()["result"]
            if not candidates:
                raise AddressNotFound(f"No properties found for {address.postcode}")
            uprn = match_address(
                address,
                candidates,
                text=lambda candidate: candidate["name"],
                uprn=lambda candidate: candidate["uprn"],
            )["uprn"]

        response = await http.post(
            _API_URL,
            json={
                "jsonrpc": "2.0",
                "id": "",
                "method": "Breckland.Whitespace.JointWasteAPI.GetBinCollectionsByUprn",
                "params": {"uprn": uprn, "environment": "live"},
            },
        )

        return [
            Collection(
                datetime.strptime(item["nextcollection"], "%d/%m/%Y %H:%M:%S").date(),
                item["collectiontype"],
            )
            for item in response.json()["result"]
        ]


SCRAPER = Breckland()
