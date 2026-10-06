"""Portsmouth: an AchieveForms lookup keyed on the UPRN, returning refuse and recycling dates."""

from __future__ import annotations

from datetime import datetime

from api.councils._base import Address, Collection, Http, Meta, Scraper, UpstreamError
from api.councils._platforms.achieveforms import first_row, init_session, run_lookup

_HOSTNAME = "my.portsmouth.gov.uk"
_FORM_URL = (
    f"https://{_HOSTNAME}/en/AchieveForms/?form_uri="
    "sandbox-publish://AF-Process-26e27e70-f771-47b1-a34d-af276075cede/"
    "AF-Stage-cd7cc291-2e59-42cc-8c3f-1f93e132a2c9/definition.json"
    "&redirectlink=%2F&cancelRedirectLink=%2F"
)
_AUTH_URL = f"https://{_HOSTNAME}/authapi/isauthenticated"
_API_URL = f"https://{_HOSTNAME}/apibroker/runLookup"


class Portsmouth(Scraper):
    meta = Meta(
        title="Portsmouth City Council",
        url="https://www.portsmouth.gov.uk",
        lads=("E06000044",),
        cases={
            "Fawcett Road": {"uprn": "1775027540"},
            "Westbourne Road": {"uprn": "1775084532"},
        },
    )
    requires = frozenset({"uprn"})
    headers = {"user-agent": "Mozilla/5.0"}

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        sid = await init_session(http, _FORM_URL, _AUTH_URL, _HOSTNAME, uri=_FORM_URL)

        data = first_row(
            await run_lookup(
                http,
                _API_URL,
                sid,
                "5e81ed10c0241",
                {"Section 1": {"col_uprn": {"value": address.need("uprn")}}},
                no_retry="true",
            )
        )
        if data is None or "listRefDatesHTML" not in data or "listRecDatesHTML" not in data:
            raise UpstreamError("Portsmouth returned no collection dates")

        rubbish_dates = data["listRefDatesHTML"].split("<p>")[0].split("<br />")
        recycling_dates = data["listRecDatesHTML"].split("<p>")[0].split("<br />")

        collections = []
        for day in rubbish_dates:
            if len(day) > 0:
                collections.append(
                    Collection(datetime.strptime(day.rstrip("* "), "%A %d %B %Y").date(), "refuse bin")
                )

        for day in recycling_dates:
            if len(day) > 0:
                collections.append(
                    Collection(datetime.strptime(day.rstrip("* "), "%A %d %B %Y").date(), "recycling bin")
                )

        return collections


SCRAPER = Portsmouth()
