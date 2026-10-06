"""Council waste portal API (`portal.waste.<council>.gov.uk/api`, `wastecollections.<council>.gov.uk/api`),
used by Dover and Haringey.

The vendor isn't named anywhere in the sites; both serve one multi-council JSON API,
told apart by a `councilId`:

1. `POST getAddressByPointId` with the UPRN as `pointId` (older UPRNs are stored
   zero-padded to 12 digits, so both forms are tried; a 404 means "not that form")
   answers with `data: [{id, ...}]`.
2. `POST getCollectionDays` with that id answers with `activeServices`, each with
   `serviceSchedules[].currentScheduledDate` (ISO).

What differs per council is the API base and id, in `WastePortalConfig`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from api.councils._base import (
    Address,
    AddressNotFound,
    Collection,
    Http,
    Platform,
    Response,
    UpstreamError,
)

_TIMEOUT = 30


@dataclass(frozen=True, slots=True, kw_only=True)
class WastePortalConfig:
    api_url: str
    """No trailing slash: "https://portal.waste.dover.gov.uk/api"."""
    council_id: str
    """"39"."""


class WastePortal(Platform[WastePortalConfig]):
    requires = frozenset({"uprn"})

    async def _point_id(self, http: Http, uprn: str) -> str:
        response: Response | None = None
        for point in dict.fromkeys((uprn, uprn.zfill(12))):
            response = await http.post(
                f"{self.config.api_url}/getAddressByPointId",
                json={"pointId": point, "councilId": self.config.council_id, "pointType": "PointAddress"},
                timeout=_TIMEOUT,
                check=False,
            )
            if response.status_code != 404:
                break
        not_found = AddressNotFound(f"{self.meta.title} has no address for UPRN {uprn}")
        if response is None or response.status_code == 404:
            raise not_found
        if response.status_code >= 400:
            raise UpstreamError(f"HTTP {response.status_code} from {response.url}")
        addresses = response.json().get("data")
        if not addresses:
            raise not_found
        try:
            return str(addresses[0]["id"])
        except (KeyError, TypeError) as exc:
            raise UpstreamError(f"{self.meta.title} address record has no id") from exc

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        point_id = await self._point_id(http, address.need("uprn"))
        response = await http.post(
            f"{self.config.api_url}/getCollectionDays",
            json={"pointId": point_id, "pointType": "PointAddress", "councilId": self.config.council_id},
            timeout=_TIMEOUT,
        )
        services: list[dict[str, Any]] = response.json().get("activeServices", [])

        collections = []
        for service in services:
            waste_type = service.get("taskTypeName") or service.get("serviceName")
            for schedule in service.get("serviceSchedules", []):
                date_text = schedule.get("currentScheduledDate")
                if not date_text:
                    continue
                try:
                    day = datetime.fromisoformat(date_text.replace("Z", "+00:00")).date()
                except ValueError as exc:
                    raise UpstreamError(f"{self.meta.title} gave an unreadable date {date_text!r}") from exc
                if not waste_type:
                    raise UpstreamError(f"{self.meta.title} service has no name: {service!r}")
                collections.append(Collection(day, waste_type))
        return collections
