"""Haringey: resolve a UPRN to a point ID, then fetch that point's collection schedule."""

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

_API = "https://wastecollections.haringey.gov.uk/api"
_COUNCIL_ID = "45"


class Haringey(Scraper):
    meta = Meta(
        title="Haringey Council",
        url="https://www.haringey.gov.uk/",
        lads=("E09000014",),
        cases={
            "Test_001": {"uprn": "100021209182"},
            "Test_002": {"uprn": "100021207181"},
            "Test_003": {"uprn": "100021202738"},
        },
    )
    requires = frozenset({"uprn"})

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        uprn = address.need("uprn")

        address_response = None
        for point in dict.fromkeys((uprn, uprn.zfill(12))):
            address_response = await http.post(
                f"{_API}/getAddressByPointId",
                json={
                    "pointId": point,
                    "councilId": _COUNCIL_ID,
                    "pointType": "PointAddress",
                },
                timeout=30,
                check=False,
            )
            if address_response.status_code != 404:
                break

        if address_response is None or address_response.status_code == 404:
            raise AddressNotFound(f"Haringey has no address for UPRN {uprn}")
        if address_response.status_code >= 400:
            raise UpstreamError(f"HTTP {address_response.status_code} from {address_response.url}")

        addresses = address_response.json().get("data", [])
        if not addresses:
            raise AddressNotFound(f"Haringey has no address for UPRN {uprn}")
        point_id = addresses[0]["id"]

        collection_response = await http.post(
            f"{_API}/getCollectionDays",
            json={
                "pointId": point_id,
                "pointType": "PointAddress",
                "councilId": _COUNCIL_ID,
            },
            timeout=30,
        )
        services = collection_response.json().get("activeServices", [])

        collections = []
        for service in services:
            waste_type = service.get("taskTypeName") or service.get("serviceName")
            for schedule in service.get("serviceSchedules", []):
                date_str = schedule.get("currentScheduledDate")
                if not date_str:
                    continue
                collections.append(
                    Collection(
                        date=datetime.fromisoformat(date_str.replace("Z", "+00:00")).date(),
                        type=waste_type,
                    )
                )

        return collections


SCRAPER = Haringey()
