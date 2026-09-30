"""Dover: resolve a UPRN through the waste portal, then fetch its collection schedule."""

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

_API = "https://portal.waste.dover.gov.uk/api"
_COUNCIL_ID = "39"


class Dover(Scraper):
    meta = Meta(
        title="Dover District Council",
        url="https://www.dover.gov.uk",
        lads=("E07000108",),
        cases={
            "200002423404": {"uprn": "200002423404"},
            "100060905828": {"uprn": "100060905828"},
        },
    )
    requires = frozenset({"uprn"})

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        uprn = address.need("uprn")

        # Older UPRNs are stored zero-padded to 12 digits, newer ones are not.
        for point in dict.fromkeys([uprn, uprn.zfill(12)]):
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

        if address_response.status_code == 404:
            raise AddressNotFound(f"Dover has no address for UPRN {uprn}")
        if address_response.status_code >= 400:
            raise UpstreamError(f"HTTP {address_response.status_code} from {address_response.url}")

        addresses = address_response.json().get("data", [])
        if not addresses:
            raise AddressNotFound(f"Dover has no address for UPRN {uprn}")
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


SCRAPER = Dover()
