"""Milton Keynes: an AchieveForms lookup keyed on the UPRN, returning collection dates."""

from __future__ import annotations

import time
from datetime import datetime

from api.councils._base import Address, Collection, Http, Meta, Scraper, UpstreamError

_SESSION_URL = (
    "https://mycouncil.milton-keynes.gov.uk/authapi/isauthenticated"
    "?uri=https%253A%252F%252Fmycouncil.milton-keynes.gov.uk%252Fen%252Fservice"
    "%252FWaste_Collection_Round_Checker&hostname=mycouncil.milton-keynes.gov.uk"
    "&withCredentials=true"
)
_API_URL = "https://mycouncil.milton-keynes.gov.uk/apibroker/runLookup"
_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json",
    "User-Agent": "Mozilla/5.0",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": "https://mycouncil.milton-keynes.gov.uk/fillform/?iframe_id=fillform-frame-1&db_id=",
}


class MiltonKeynes(Scraper):
    meta = Meta(
        title="Milton Keynes",
        url="https://mycouncil.milton-keynes.gov.uk/en/service/Waste_Collection_Round_Checker",
        lads=("E06000042",),
        cases={},
    )
    requires = frozenset({"uprn"})

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        uprn = address.need("uprn")
        session_response = await http.get(_SESSION_URL)
        sid = session_response.json()["auth-session"]

        params = {
            "id": "64d9feda3a507",
            "repeat_against": "",
            "noRetry": "false",
            "getOnlyTokens": "undefined",
            "log_id": "",
            "app_name": "AF-Renderer::Self",
            "_": str(int(time.time() * 1000)),
            "sid": sid,
        }
        response = await http.post(
            _API_URL,
            json={"formValues": {"Section 1": {"uprnCore": {"value": uprn}}}},
            headers=_HEADERS,
            params=params,
        )

        data = response.json()
        if data.get("status") == "error":
            message = data.get("error", {}).get("message", "Unknown API error")
            raise UpstreamError(f"Milton Keynes API error: {message}")

        rows_data = data.get("integration", {}).get("transformed", {}).get("rows_data")
        if not rows_data or not isinstance(rows_data, dict):
            raise UpstreamError("No collection data returned from API")

        collections = []
        for item in rows_data.values():
            try:
                collection_date = datetime.strptime(item["NextInstance"], "%Y-%m-%d").date()
            except (KeyError, ValueError):
                continue
            bin_type = item.get("AssetTypeName")
            if not bin_type:
                continue
            collections.append(Collection(collection_date, bin_type))
        return collections


SCRAPER = MiltonKeynes()
