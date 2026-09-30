"""Camden: a UPRN-keyed JSON API returns upcoming domestic collection dates."""

from __future__ import annotations

from datetime import date, datetime

from api.councils._base import (
    Address,
    AddressNotFound,
    Collection,
    Http,
    Meta,
    Scraper,
    UpstreamError,
)

_BASE_URL = "https://recyclingandrubbishcollections.camden.gov.uk"
_API_CALENDAR_DATA = f"{_BASE_URL}/api/getCalendarData"
_COUNCIL_ID = "27"


class Camden(Scraper):
    meta = Meta(
        title="London Borough of Camden",
        url="https://www.camden.gov.uk/",
        lads=("E09000007",),
        cases={"Red Lion Street": {"uprn": "5121151"}},
    )
    requires = frozenset({"uprn"})

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        uprn = address.need("uprn")
        response = await http.post(
            _API_CALENDAR_DATA,
            json={"councilId": _COUNCIL_ID, "uprn": uprn},
            headers={"content-type": "application/json", "x-recaptcha-token": ""},
            timeout=30,
            check=False,
        )
        if response.status_code == 404:
            raise AddressNotFound(f"Camden has no calendar data for UPRN {uprn}")
        if response.status_code >= 400:
            raise UpstreamError(f"HTTP {response.status_code} from {response.url}")

        data = response.json()
        if data.get("message") != "OK":
            raise UpstreamError(
                f"API advised error (HTTP {response.status_code}, UPRN {uprn}): {data.get('message')}"
            )

        collections = []
        today = date.today()

        for data_item in data.get("data", []):
            for record in data_item.get("records", []):
                scheduled_date = record.get("actual_scheduled_date")
                service = record.get("service", "").strip()
                if not scheduled_date or not service:
                    continue

                collection_date = datetime.fromisoformat(
                    scheduled_date.replace("Z", "+00:00")
                ).date()
                if collection_date < today:
                    continue

                collections.append(Collection(collection_date, service))

        return collections


SCRAPER = Camden()
