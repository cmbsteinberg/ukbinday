"""Fermanagh and Omagh: search properties by postcode, then fetch their collection calendar."""

from __future__ import annotations

from datetime import datetime

from api.councils._base import (
    Address,
    AddressNotFound,
    Collection,
    Http,
    InputError,
    Meta,
    Scraper,
    match_address,
    soup,
)

API_URL = "https://fermanaghomagh.isl-fusion.com"


class FermanaghAndOmagh(Scraper):
    meta = Meta(
        title="Fermanagh and Omagh District Council",
        url="https://www.fermanaghomagh.com/",
        lads=("N09000006",),
        cases={
            "Test_001": {"postcode": "BT78 1RG", "house_number": "1"},
            "Test_002": {"postcode": "BT78 5AA", "house_number": "10"},
            "Test_003": {"property_id": "GMtpf6Tk1glK57Zj"},
        },
    )
    requires = frozenset()

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        property_id = address.get("property_id")

        if not property_id:
            if address.postcode is None or address.house_number is None:
                raise InputError(
                    "Must provide either a property ID or both the Postcode and House Number"
                )

            response = await http.get(f"{API_URL}/address/{address.postcode}")
            try:
                address_list = response.json().get("html")
            except (AttributeError, TypeError, ValueError):
                raise AddressNotFound(
                    f"No addresses found for postcode {address.postcode}"
                ) from None

            if not isinstance(address_list, (str, bytes)):
                raise AddressNotFound(
                    f"No addresses found for postcode {address.postcode}"
                )

            candidates: list[tuple[str, str]] = []
            for item in soup(address_list).find_all("li"):
                link = item.find_all("a")[0]
                candidate_id = (
                    link.attrs["href"].replace("/view", "").replace("/", "")
                )
                candidates.append((link.text, candidate_id))

            property_id = match_address(
                address,
                candidates,
                text=lambda candidate: candidate[0],
            )[1]

        today = datetime.today().date()
        response = await http.get(
            f"{API_URL}/calendar/{property_id}/{today.strftime('%Y-%m-%d')}"
        )

        try:
            collections_by_date = response.json()["nextCollections"]["collections"]
        except (AttributeError, KeyError, TypeError, ValueError):
            raise ValueError("No collection data in response") from None

        collections = []
        for collection in collections_by_date.values():
            collection_date = datetime.strptime(
                collection["date"], "%Y-%m-%d"
            ).date()

            for bin_data in collection["collections"].values():
                collections.append(Collection(collection_date, bin_data["name"]))

        return collections


SCRAPER = FermanaghAndOmagh()
