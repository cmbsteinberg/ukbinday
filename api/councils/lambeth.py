"""Lambeth: looks up the next collection dates from its Whitespace service by UPRN."""

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
)

_API_URL = "https://wasteservice.lambeth.gov.uk/WhitespaceComms/GetServicesByUprn"
_ALLOWED_SERVICES = {
    "Domestic Food Collection Service",
    "Domestic Recycling Collection Service",
    "Domestic Refuse Collection Service",
    "Domestic Garden Collection Service",
}


class Lambeth(Scraper):
    meta = Meta(
        title="London Borough of Lambeth",
        url="https://www.lambeth.gov.uk/",
        lads=("E09000022",),
        cases={
            "Sternhold Avenue": {"uprn": "100021893293"},
            "Sibella Road": {"uprn": "100021889496"},
            "Hoadly Road": {"uprn": "100021852695"},
        },
    )
    requires = frozenset({"uprn"})
    headers = {"User-Agent": "Mozilla/5.0"}

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        uprn = address.need("uprn")
        response = await http.post(
            _API_URL,
            json={
                "uprn": str(uprn),
                "includeEventTypes": False,
                "includeFlags": True,
            },
            headers={"Content-Type": "application/json"},
            timeout=30,
        )

        try:
            data = response.json()
        except ValueError as exc:
            raise UpstreamError("Invalid JSON response from Lambeth") from exc

        services = data.get("SiteServices")
        if not services:
            raise AddressNotFound(f"Lambeth has no services for UPRN {uprn}")

        collections = []
        for item in services:
            service_name = item.get("ServiceDescription")
            next_date = item.get("NextCollectionDate")

            if not service_name or not next_date or service_name not in _ALLOWED_SERVICES:
                continue

            try:
                collection_date = datetime.strptime(next_date, "%d/%m/%Y").date()
            except ValueError:
                continue

            collections.append(Collection(collection_date, service_name))

        if not collections:
            raise UpstreamError("No valid waste collection entries found")

        return collections


SCRAPER = Lambeth()
