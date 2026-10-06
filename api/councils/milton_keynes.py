"""Milton Keynes: an AchieveForms lookup keyed on the UPRN, returning collection dates."""

from __future__ import annotations

from datetime import datetime

from api.councils._base import Address, Collection, Http, Meta, Scraper, UpstreamError
from api.councils._platforms.achieveforms import init_session, rows, run_lookup

_HOSTNAME = "mycouncil.milton-keynes.gov.uk"
_AUTH_URL = f"https://{_HOSTNAME}/authapi/isauthenticated"
_FORM_URI = f"https://{_HOSTNAME}/en/service/Waste_Collection_Round_Checker"
_API_URL = f"https://{_HOSTNAME}/apibroker/runLookup"
_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json",
    "User-Agent": "Mozilla/5.0",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": f"https://{_HOSTNAME}/fillform/?iframe_id=fillform-frame-1&db_id=",
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
        sid = await init_session(http, None, _AUTH_URL, _HOSTNAME, uri=_FORM_URI)

        rows_data = rows(
            await run_lookup(
                http,
                _API_URL,
                sid,
                "64d9feda3a507",
                {"Section 1": {"uprnCore": {"value": uprn}}},
                headers=_HEADERS,
            )
        )
        if not rows_data:
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
