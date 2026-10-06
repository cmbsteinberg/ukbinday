"""Hounslow: authenticate with AchieveForms, fetch a Bartec token, then request the UPRN's collections."""

from __future__ import annotations

import json
from datetime import datetime, timedelta

from api.councils._base import Address, Collection, Http, Meta, Scraper, UpstreamError
from api.councils._platforms.achieveforms import first_row, init_session, run_lookup

_HOSTNAME = "my.hounslow.gov.uk"
_AUTH_URL = f"https://{_HOSTNAME}/authapi/isauthenticated"
_FORM_URI = f"https://{_HOSTNAME}/service/Waste_and_recycling_collections"
_API_URL = f"https://{_HOSTNAME}/apibroker/runLookup"
_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json",
    "User-Agent": "Mozilla/5.0",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": f"https://{_HOSTNAME}/fillform/?iframe_id=fillform-frame-1&db_id=",
}


class Hounslow(Scraper):
    meta = Meta(
        title="Hounslow",
        url="https://my.hounslow.gov.uk/service/Waste_and_recycling_collections",
        lads=("E09000018",),
        cases={},
    )
    requires = frozenset({"uprn"})

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        uprn = address.need("uprn")
        sid = await init_session(http, None, _AUTH_URL, _HOSTNAME, uri=_FORM_URI)

        token_row = first_row(
            await run_lookup(http, _API_URL, sid, "655f4290810cf", None, no_retry="true", headers=_HEADERS)
        )
        if token_row is None or "bartecToken" not in token_row:
            raise UpstreamError("Hounslow gave no Bartec token")

        now = datetime.now()
        row = first_row(
            await run_lookup(
                http,
                _API_URL,
                sid,
                "659eb39b66d5a",
                {
                    "Your address": {
                        "searchUPRN": {"value": uprn},
                        "bartecToken": {"value": token_row["bartecToken"]},
                        "searchFromDate": {"value": now.strftime("%Y-%m-%d")},
                        "searchToDate": {"value": (now + timedelta(days=30)).strftime("%Y-%m-%d")},
                    },
                },
                headers=_HEADERS,
            )
        )
        if row is None or "jobsJSON" not in row:
            raise UpstreamError("Hounslow returned no collection jobs")

        result: list[Collection] = []
        for collection in json.loads(row["jobsJSON"]):
            bin_type = collection["jobType"]
            if not bin_type:
                continue
            try:
                day = datetime.strptime(collection["jobDate"], "%Y-%m-%d").date()
            except ValueError:
                continue
            result.append(Collection(day, bin_type))
        return result


SCRAPER = Hounslow()
