"""Reigate & Banstead: an AchieveForms lookup returns XML containing the collection schedule HTML."""

from __future__ import annotations

from datetime import datetime, timedelta

from api.councils._base import (
    Address,
    Collection,
    Http,
    Meta,
    Scraper,
    UpstreamError,
    soup,
)
from api.councils._platforms.achieveforms import data_rows, init_session, run_lookup

_HEADERS = {"user-agent": "Mozilla/5.0"}
_HOSTNAME = "my.reigate-banstead.gov.uk"
_AUTH_URL = f"https://{_HOSTNAME}/authapi/isauthenticated"
_FORM_URI = f"https://{_HOSTNAME}/service/Bins_and_recycling___collections_calendar"
_API_URL = f"https://{_HOSTNAME}/apibroker/runLookup"


class ReigateAndBanstead(Scraper):
    meta = Meta(
        title="Reigate & Banstead Borough Council",
        url="https://reigate-banstead.gov.uk",
        lads=("E07000211",),
        cases={
            "Test_001": {"uprn": "68110755"},
            "Test_003": {"uprn": "68101147"},
        },
    )
    requires = frozenset({"uprn"})
    headers = _HEADERS

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        sid = await init_session(http, None, _AUTH_URL, _HOSTNAME, uri=_FORM_URI)

        # Both lookups answer XML in `data`: a token, then the schedule as escaped HTML.
        token_rows = data_rows(await run_lookup(http, _API_URL, sid, "595ce0f243541", None, no_retry="true"))
        if not token_rows or "Token" not in token_rows[0]:
            raise UpstreamError("Reigate & Banstead gave no token")

        min_date = datetime.today().strftime("%Y-%m-%d")
        max_date = (datetime.today() + timedelta(days=28)).strftime("%Y-%m-%d")
        schedule_rows = data_rows(
            await run_lookup(
                http,
                _API_URL,
                sid,
                "609d41ca89251",
                {
                    "Section 1": {
                        "uprnPWB": {"value": address.need("uprn")},
                        "minDate": {"value": min_date},
                        "maxDate": {"value": max_date},
                        "tokenString": {"value": token_rows[0]["Token"]},
                    }
                },
                no_retry="true",
            )
        )
        if not schedule_rows or "root" not in schedule_rows[0]:
            raise UpstreamError("Reigate & Banstead returned no collection schedule")
        rowdata = soup(schedule_rows[0]["root"])
        datedata = rowdata.find_all("h3")
        bindata = rowdata.find_all("ul")

        collections = []
        for index, item in enumerate(bindata):
            bin_date = datedata[index].text.strip()
            for bin_name in item.find_all("span"):
                collections.append(
                    Collection(
                        datetime.strptime(bin_date, "%A %d %B %Y").date(),
                        bin_name.text.strip(),
                    )
                )

        return collections


SCRAPER = ReigateAndBanstead()
