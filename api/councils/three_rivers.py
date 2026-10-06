"""Three Rivers: an AchieveForms token lookup followed by a UPRN-based collection schedule."""

from __future__ import annotations

from datetime import datetime, timedelta

from api.councils._base import Address, Collection, Http, Meta, Scraper, UpstreamError
from api.councils._platforms.achieveforms import (
    first_row,
    init_session,
    rows,
    run_lookup,
)

_HOSTNAME = "my.threerivers.gov.uk"
_HOST = f"https://{_HOSTNAME}"
_AUTH_URL = f"{_HOST}/authapi/isauthenticated"
_FORM_URI = (
    f"{_HOST}/en/AchieveForms/?mode=fill&consentMessage=yes"
    "&form_uri=sandbox-publish://AF-Process-52df96e3-992a-4b39-bba3-06cfaabcb42b/"
    "AF-Stage-01ee28aa-1584-442c-8d1f-119b6e27114a/definition.json&process=1"
    "&process_uri=sandbox-processes://AF-Process-52df96e3-992a-4b39-bba3-06cfaabcb42b"
    "&process_id=AF-Process-52df96e3-992a-4b39-bba3-06cfaabcb42b&noLoginPrompt=1"
)
# This portal serves lookups from /apibroker/?api=RunLookup rather than /apibroker/runLookup.
_API_URL = f"{_HOST}/apibroker/"
_API_PARAMS = {"api": "RunLookup"}
_TOKEN_LOOKUP_ID = "58986058d4be0"
_SCHEDULE_LOOKUP_ID = "58ac332f9e831"
_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json",
    "User-Agent": "Mozilla/5.0",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": f"{_HOST}/fillform/?iframe_id=fillform-frame-1&db_id=",
}


class ThreeRivers(Scraper):
    meta = Meta(
        title="Three Rivers District Council",
        url="https://www.threerivers.gov.uk",
        lads=("E07000102",),
        cases={"Test_001": {"uprn": "100080913662"}},
    )
    requires = frozenset({"uprn"})
    headers = _HEADERS

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        uprn = address.need("uprn")
        now = datetime.now()
        two_weeks = now + timedelta(days=14)

        sid = await init_session(http, None, _AUTH_URL, _HOSTNAME, uri=_FORM_URI)

        token_row = first_row(
            await run_lookup(
                http,
                _API_URL,
                sid,
                _TOKEN_LOOKUP_ID,
                {
                    "Your address details": {
                        "UPRN": {"value": uprn},
                        "todaysdate": {"value": now.strftime("%Y-%m-%dT00:00:00")},
                    }
                },
                no_retry="true",
                params=_API_PARAMS,
            )
        )
        if token_row is None or "token" not in token_row:
            raise UpstreamError("Three Rivers gave no token")

        rows_data = rows(
            await run_lookup(
                http,
                _API_URL,
                sid,
                _SCHEDULE_LOOKUP_ID,
                {
                    "Your address details": {
                        "UPRN": {"value": uprn},
                        "todaysdate": {"value": now.strftime("%Y-%m-%dT00:00:00")},
                        "twoweeks": {"value": two_weeks.strftime("%Y-%m-%dT00:00:00")},
                    },
                    "Your collection dates": {"token": {"value": token_row["token"]}},
                },
                params=_API_PARAMS,
            )
        )
        if not rows_data:
            return []  # the council lists nothing for this property

        collections: list[Collection] = []
        for row in rows_data.values():
            job_name = row.get("JobName", "")
            date_str = row.get("Date", "")
            if not job_name or not date_str:
                continue
            try:
                day = datetime.strptime(date_str, "%d-%m-%Y").date()
            except ValueError:
                continue
            collections.append(Collection(date=day, type=job_name))

        return collections


SCRAPER = ThreeRivers()
