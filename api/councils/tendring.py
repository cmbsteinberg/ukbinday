"""Tendring: an AchieveForms lookup keyed on the UPRN."""

from __future__ import annotations

from datetime import datetime
from time import time_ns

from api.councils._base import Address, Collection, Http, Meta, Scraper

_HOST = "https://tendring-self.achieveservice.com"
_AUTH_URL = (
    f"{_HOST}/authapi/isauthenticated"
    "?uri=https%253A%252F%252Ftendring-self.achieveservice.com%252Fen%252Fservice%252FRubbish_and_recycling_collection_days"
    "&hostname=tendring-self.achieveservice.com&withCredentials=true"
)
_API_URL = f"{_HOST}/apibroker/runLookup"
_SCHEDULE_LOOKUP_ID = "6347acbadc425"
_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json",
    "User-Agent": "Mozilla/5.0",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": f"{_HOST}/fillform/?iframe_id=fillform-frame-1&db_id=",
}
_DATE_FIELDS = {
    "nextResidualCollection": "Residual waste",
    "nextRedCollection": "Red recycling box",
    "nextGreenCollection": "Green recycling box",
    "nextFoodCollection": "Food waste",
    "nextGardenCollection": "Garden waste",
}


class Tendring(Scraper):
    meta = Meta(
        title="Tendring District Council",
        url="https://www.tendring.gov.uk",
        lads=("E07000076",),
        cases={"Test_001": {"uprn": "100090604247"}},
    )
    requires = frozenset({"uprn"})
    headers = _HEADERS

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        auth = await http.get(_AUTH_URL)
        sid = auth.json()["auth-session"]

        payload = {
            "formValues": {
                "Select address": {
                    "selectedUPRN": {"value": address.need("uprn")},
                    "selectAddress": {"value": address.need("uprn")},
                }
            }
        }
        params = {
            "id": _SCHEDULE_LOOKUP_ID,
            "repeat_against": "",
            "noRetry": "true",
            "getOnlyTokens": "undefined",
            "log_id": "",
            "app_name": "AF-Renderer::Self",
            "_": str(time_ns() // 1_000_000),
            "sid": sid,
        }

        response = await http.post(_API_URL, params=params, json=payload)
        rows_data = response.json().get("integration", {}).get("transformed", {}).get("rows_data", {})
        if not rows_data:
            return []

        row = rows_data.get("0", {})
        collections = []
        for field, bin_type in _DATE_FIELDS.items():
            date_str = row.get(field)
            if not date_str:
                continue
            try:
                day = datetime.strptime(date_str.split()[0], "%d/%m/%Y").date()
            except (ValueError, IndexError):
                continue
            collections.append(Collection(day, bin_type))

        return collections


SCRAPER = Tendring()
