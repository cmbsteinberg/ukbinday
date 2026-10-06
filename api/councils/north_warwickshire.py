"""North Warwickshire: AchieveForms lookups keyed on the UPRN."""

from __future__ import annotations

from datetime import datetime, timedelta

from api.councils._base import (
    Address,
    Collection,
    Http,
    Meta,
    Scraper,
    UpstreamError,
)
from api.councils._platforms.achieveforms import (
    first_row,
    init_session,
    rows,
    run_lookup,
)

_HOSTNAME = "nwarks-ss.achieveservice.com"
_AUTH_URL = f"https://{_HOSTNAME}/authapi/isauthenticated"
_API_URL = f"https://{_HOSTNAME}/apibroker/runLookup"
_TOKEN_LOOKUP_ID = "695fc5d469d65"
_LOOKUP_IDS = ("6964f19aac313", "6964f19d080c5", "6964f19bc2e2e", "695fc85344bb3")
_REQUEST_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json",
    "User-Agent": "Mozilla/5.0",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": f"https://{_HOSTNAME}/fillform/?iframe_id=fillform-frame-1&db_id=",
}


class NorthWarwickshire(Scraper):
    meta = Meta(
        title="North Warwickshire",
        url="https://www.northwarks.gov.uk",
        lads=("E07000218",),
        cases={},
    )
    requires = frozenset({"uprn"})

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        uprn = address.need("uprn")

        sid = await init_session(http, None, _AUTH_URL, _HOSTNAME, uri=f"https://{_HOSTNAME}/")

        token_row = first_row(
            await run_lookup(
                http,
                _API_URL,
                sid,
                _TOKEN_LOOKUP_ID,
                {"Collection Details": {"testOrLive": {"value": "Live"}}},
                no_retry="true",
                headers=_REQUEST_HEADERS,
            )
        )
        if token_row is None or "AuthenticateResponse" not in token_row:
            raise UpstreamError("North Warwickshire gave no AuthenticateResponse")

        now = datetime.now()
        form_values = {
            "Collection Details": {
                "AuthenticateResponse": {"value": token_row["AuthenticateResponse"]},
                "uprn": {"value": uprn},
                "dateTodayFormatted": {"value": now.strftime("%Y-%m-%d")},
                "date4WeeksFormatted": {"value": (now + timedelta(weeks=12)).strftime("%Y-%m-%d")},
            },
        }

        groups = [
            rows(
                await run_lookup(
                    http, _API_URL, sid, lookup_id, form_values, headers=_REQUEST_HEADERS
                )
            )
            for lookup_id in _LOOKUP_IDS
        ]

        collections: list[Collection] = []
        for group in groups:
            if not group:
                continue
            for item in group.values():
                bin_type = item["JobName"].strip()
                date_text = item["Date"]
                try:
                    if "-" in date_text:
                        day = datetime.strptime(date_text, "%Y-%m-%d").date()
                    elif "/" in date_text:
                        day = datetime.strptime(date_text, "%d/%m/%Y").date()
                    else:
                        continue
                except ValueError:
                    continue
                collections.append(Collection(day, bin_type))

        return collections


SCRAPER = NorthWarwickshire()
