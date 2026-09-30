"""Fife Council: authenticate, then request bin collections by UPRN."""

from __future__ import annotations

from datetime import datetime

from api.councils._base import (
    Address,
    Collection,
    Http,
    InputError,
    Meta,
    Scraper,
    UpstreamError,
)

_API_BASE_URL = "https://fife.form.uk.empro.verintcloudservices.com/api"
_API_URL = f"{_API_BASE_URL}/custom"
_AUTH_URL = f"{_API_BASE_URL}/citizen"
_DATE_FORMAT = "%A, %B %d, %Y"
_REQUEST_TIMEOUT = 10


class Fife(Scraper):
    meta = Meta(
        title="Fife Council",
        url="https://www.fife.gov.uk",
        lads=("S12000047",),
        cases={
            "SANDYHILL ROAD, ST ANDREWS": {"uprn": "320069186"},
            "CERES ROAD, PITSCOTTIE": {"uprn": "320063641"},
            "SHORE ROAD, BALMALCOLM": {"uprn": "320083539"},
        },
    )
    requires = frozenset({"uprn"})

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        uprn = address.need("uprn")

        auth_response = await http.get(
            _AUTH_URL,
            params={"preview": "false", "locale": "en"},
            timeout=_REQUEST_TIMEOUT,
        )
        auth_token = auth_response.headers.get("Authorization")
        if not auth_token:
            raise UpstreamError("No authorization token received from Fife Council")

        api_response = await http.post(
            _API_URL,
            params={
                "action": "powersuite_bin_calendar_collections",
                "actionedby": "bin_calendar",
                "loadform": True,
                "access": "citizen",
                "locale": "en",
            },
            json={"name": "bin_calendar", "data": {"uprn": uprn}},
            headers={"Authorization": auth_token},
            timeout=_REQUEST_TIMEOUT,
        )

        response_data = api_response.json()
        data = response_data.get("data", {})

        if data.get("results_returned") == "false":
            raise InputError(f"No results returned for UPRN: {uprn}")

        collections = data.get("tab_collections", [])
        if not collections:
            raise InputError(f"No collection data found for UPRN: {uprn}")

        entries: list[Collection] = []
        for collection in collections:
            try:
                date_str = collection.get("date")
                if not date_str:
                    continue

                day = datetime.strptime(date_str, _DATE_FORMAT).date()
                collection_type = collection.get("type", "")
                entries.append(Collection(day, collection_type))
            except (ValueError, KeyError):
                continue

        return entries


SCRAPER = Fife()
