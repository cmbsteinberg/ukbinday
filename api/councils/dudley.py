"""Dudley: an AchieveForms lookup keyed on the UPRN."""

from __future__ import annotations

from datetime import datetime

from api.councils._base import (
    Address,
    Collection,
    Http,
    Meta,
    Scraper,
    UpstreamError,
)
from api.councils._platforms.achieveforms import first_row, init_session, run_lookup

_HOSTNAME = "my.dudley.gov.uk"
_AUTH_URL = f"https://{_HOSTNAME}/authapi/isauthenticated"
_FORM_URI = (
    f"https://{_HOSTNAME}/en/AchieveForms/?form_uri=sandbox-publish://AF-Process-373f5628-9aae-4e9e-ae09-ea7cd0588201/"
    "AF-Stage-52ec040b-10e6-440f-b964-23f924741496/definition.json"
    "&redirectlink=%2Fen&cancelRedirectLink=%2Fen&consentMessage=yes"
)
_API_URL = f"https://{_HOSTNAME}/apibroker/runLookup"
_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json",
    "User-Agent": "Mozilla/5.0",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": f"https://{_HOSTNAME}/fillform/?iframe_id=fillform-frame-1&db_id=",
}
_BIN_TYPES = {
    "refuseDate": "Refuse",
    "recyclingDate": "Recycling",
    "gardenDate": "Garden Waste",
}


class Dudley(Scraper):
    meta = Meta(
        title="Dudley",
        url="https://my.dudley.gov.uk",
        lads=("E08000027",),
        cases={},
    )
    requires = frozenset({"uprn"})

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        uprn = address.need("uprn")
        sid = await init_session(http, None, _AUTH_URL, _HOSTNAME, uri=_FORM_URI)

        row = first_row(
            await run_lookup(
                http,
                _API_URL,
                sid,
                "64899d4c2574c",
                {"My bins": {"uprnToCheck": {"value": uprn}}},
                no_retry="true",
                headers=_HEADERS,
            )
        )
        if row is None:
            raise UpstreamError("Dudley's lookup returned no row for this UPRN")

        collections = []
        for key, value in row.items():
            if key.endswith("Date") and not key.endswith("EndDate") and value:
                try:
                    day = datetime.strptime(value, "%Y-%m-%d").date()
                except ValueError:
                    continue
                collections.append(Collection(day, _BIN_TYPES.get(key, key)))
        return collections


SCRAPER = Dudley()
