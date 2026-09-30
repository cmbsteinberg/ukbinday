from datetime import datetime

import httpx

from api.compat.hacs import Collection, Icons  # type: ignore[attr-defined]
from api.compat.hacs.exceptions import SourceArgumentNotFound

TITLE = "Dover District Council"
DESCRIPTION = "Source for Dover District Council."
URL = "https://www.dover.gov.uk"
TEST_CASES = {
    "200002423404": {"uprn": 200002423404},
    "100060905828": {"uprn": "100060905828"},
}

ICON_MAP = {
    "Garden Waste Collection": Icons.GARDEN,
    "Food Collection": Icons.BIO_KITCHEN,
    "Refuse Collection": Icons.GENERAL_WASTE,
    "Paper/Card Collection": Icons.PAPER,
    "Recycling Collection": Icons.RECYCLING,
}

API = "https://portal.waste.dover.gov.uk/api"
COUNCIL_ID = "39"


class Source:
    def __init__(self, uprn):
        self._uprn = str(uprn).strip()

    async def fetch(self):
        session = httpx.AsyncClient(follow_redirects=True)

        # Step 1: resolve the UPRN to the internal point id.
        # Older UPRNs are stored zero-padded to 12 digits, newer ones are not,
        # so try the UPRN as given and then the padded form.
        for point in dict.fromkeys([self._uprn, self._uprn.zfill(12)]):
            address_response = await session.post(
                f"{API}/getAddressByPointId",
                json={
                    "pointId": point,
                    "councilId": COUNCIL_ID,
                    "pointType": "PointAddress",
                },
                timeout=30,
            )
            if address_response.status_code != 404:
                break
        if address_response.status_code == 404:
            raise SourceArgumentNotFound("uprn", self._uprn)
        address_response.raise_for_status()
        addresses = address_response.json().get("data", [])
        if not addresses:
            raise SourceArgumentNotFound("uprn", self._uprn)
        point_id = addresses[0]["id"]

        # Step 2: fetch the collection schedule for that point id.
        collection_response = await session.post(
            f"{API}/getCollectionDays",
            json={
                "pointId": point_id,
                "pointType": "PointAddress",
                "councilId": COUNCIL_ID,
            },
            timeout=30,
        )
        collection_response.raise_for_status()
        services = collection_response.json().get("activeServices", [])

        entries = []
        for service in services:
            waste_type = service.get("taskTypeName") or service.get("serviceName")
            for schedule in service.get("serviceSchedules", []):
                date_str = schedule.get("currentScheduledDate")
                if not date_str:
                    continue
                entries.append(
                    Collection(
                        date=datetime.fromisoformat(
                            date_str.replace("Z", "+00:00")
                        ).date(),
                        t=waste_type,
                        icon=ICON_MAP.get(waste_type),
                    )
                )

        return entries
