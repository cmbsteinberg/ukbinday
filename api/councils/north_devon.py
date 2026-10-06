"""North Devon: AchieveForms lookups resolve a UPRN, obtain a live token, then read service dates."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from api.councils._base import Address, Collection, Http, Meta, Scraper, UpstreamError
from api.councils._platforms.achieveforms import (
    data_rows,
    first_row,
    init_session,
    run_lookup,
)

TITLE = "North Devon Council"
URL = "https://www.northdevon.gov.uk"

HOST = "https://my.northdevon.gov.uk"
HOSTNAME = "my.northdevon.gov.uk"
AUTH_URL = f"{HOST}/authapi/isauthenticated"
FORM_URI = f"{HOST}/service/WasteRecyclingCollectionCalendar"
API_URL = f"{HOST}/apibroker/runLookup"

USRN_LOOKUP_ID = "65141c7c38bd0"
TOKEN_LOOKUP_ID = "59e606ee95b7a"
DATE_RANGE_LOOKUP_ID = "6255925ca44cb"
SERVICE_DETAILS_LOOKUP_ID = "61091d927cd81"

HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json",
    "User-Agent": "Mozilla/5.0",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": f"{HOST}/fillform/?iframe_id=fillform-frame-1&db_id=",
}


def _service_details(reply: dict[str, Any]) -> list[str]:
    """The ServiceDetail column of every row in the lookup's XML payload."""
    return [
        detail
        for row in data_rows(reply)
        if (detail := row.get("ServiceDetail", "").strip())
    ]


def _parse_service_detail(text: str) -> Collection | None:
    detail = text.strip()
    if detail.lower().startswith("empty bin "):
        detail = detail[len("empty bin ") :]
    try:
        bin_type, day, month, year = detail.rsplit("/", 3)
    except ValueError:
        return None
    bin_type = bin_type.strip()
    if not bin_type:
        return None
    try:
        collection_date = datetime(int(year), int(month), int(day)).date()
    except ValueError:
        return None
    return Collection(date=collection_date, type=bin_type)


class NorthDevon(Scraper):
    meta = Meta(
        title=TITLE,
        url=URL,
        lads=("E07000043",),
        cases={"Test_001": {"uprn": "100040249471", "postcode": "EX31 2LE"}},
    )
    requires = frozenset({"uprn"})
    headers = HEADERS

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        today = date.today()
        uprn = address.need("uprn")
        form: dict[str, Any] = {
            "Your address": {
                "qsUPRN": {"value": uprn},
                "postcode_search": {"value": address.postcode_compact or ""},
                "chooseAddress": {"value": uprn},
                "uprnfromlookup": {"value": uprn},
                "UPRNMF": {"value": uprn},
                "FULLADDR2": {"value": ""},
            },
            "Calendar": {
                "FULLADDR": {"value": ""},
                "token": {"value": ""},
                "uPRN": {"value": uprn},
                "calstartDate": {"value": ""},
                "calendDate": {"value": ""},
                "UPRN": {"value": uprn},
                "liveToken": {"value": ""},
                "USRN": {"value": ""},
                "StartDate": {"value": (today - timedelta(days=31)).isoformat()},
                "EndDate": {"value": (today + timedelta(days=1)).isoformat()},
            },
            "Print version": {"OutText2": {"value": ""}},
        }
        address_form = form["Your address"]
        calendar = form["Calendar"]

        sid = await init_session(http, None, AUTH_URL, HOSTNAME, uri=FORM_URI)

        async def call(lookup_id: str, no_retry: str = "true") -> dict[str, Any]:
            return await run_lookup(http, API_URL, sid, lookup_id, form, no_retry=no_retry)

        usrn_row = first_row(await call(USRN_LOOKUP_ID)) or {}
        usrn = usrn_row.get("USRN", "")
        if not usrn:
            return []  # the council has no street for this property
        address_form["FULLADDR2"] = {"value": usrn_row.get("FULLADDR2", "")}
        calendar["USRN"] = {"value": usrn}

        token = (first_row(await call(TOKEN_LOOKUP_ID)) or {}).get("liveToken", "")
        if not token:
            raise UpstreamError("North Devon gave no live token")
        calendar["liveToken"] = {"value": token}
        calendar["token"] = {"value": token}

        date_row = first_row(await call(DATE_RANGE_LOOKUP_ID)) or {}
        calendar["calstartDate"] = {"value": date_row.get("calstartDate", "")}
        calendar["calendDate"] = {"value": date_row.get("calendDate", "")}

        details = _service_details(await call(SERVICE_DETAILS_LOOKUP_ID, no_retry="false"))

        collections: list[Collection] = []
        for detail in details:
            collection = _parse_service_detail(detail)
            if collection is not None:
                collections.append(collection)
        return collections


SCRAPER = NorthDevon()
