"""Angus: initialise the MyAngus session, search by postcode, then fetch collections by UPRN."""

from __future__ import annotations

import re
from datetime import datetime

from api.councils._base import (
    Address,
    Collection,
    Http,
    Meta,
    Scraper,
    UpstreamError,
)
from api.councils._platforms.achieveforms import data_rows, run_lookup

_START_URL = "https://myangus.angus.gov.uk/service/Bin_collection_dates_V3"
_API_URL = "https://myangus.angus.gov.uk/apibroker/runLookup"
_SEARCH_LOOKUP_ID = "686cdfffd9945"
_SCHEDULE_LOOKUP_ID = "66587d491feab"
_FORM = {
    "formId": "AF-Form-37d4dfe5-4407-4f21-848e-ef456949faf2",
    "processId": "AF-Process-a15a2788-7daa-46f0-96c4-75acb62d4496",
    "stage_id": "AF-Stage-6d652139-a8ac-4e28-97b6-0e02ed369933",
    "stage_name": "Stage 1",
}
_SESSION_ID = re.compile(r"[?&]sid=([a-f0-9]{32})")
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,*/*;q=0.8"
    ),
}
_POST_HEADERS = {
    "Content-Type": "application/json",
    "X-Requested-With": "XMLHttpRequest",
    "Origin": "https://myangus.angus.gov.uk",
}


class Angus(Scraper):
    meta = Meta(
        title="Angus Council",
        url="https://www.angus.gov.uk",
        lads=("S12000041",),
        cases={"Test": {"uprn": "117097214", "postcode": "DD11 2RH"}},
    )
    requires = frozenset({"uprn", "postcode"})
    headers = _HEADERS

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        uprn = address.need("uprn")
        postcode = address.need("postcode")
        postcode_search = postcode.replace(" ", "").lower()

        r1 = await http.get(_START_URL)
        match = _SESSION_ID.search(r1.text)
        if not match:
            raise UpstreamError("Could not find Session ID (sid) on Angus Council page")
        sid = match.group(1)

        now = datetime.now()
        http.cookies.set(
            "localtime",
            now.strftime("%Y-%m-%d %H:%M:%S"),
            domain="myangus.angus.gov.uk",
        )
        http.cookies.set(
            "fs-timezone",
            "Europe/London",
            domain="myangus.angus.gov.uk",
        )

        post_headers = {**_POST_HEADERS, "Referer": r1.url}
        # The form runs the postcode search first. Its reply isn't read, but the
        # schedule lookup is made in the session that has asked.
        await run_lookup(
            http,
            _API_URL,
            sid,
            _SEARCH_LOOKUP_ID,
            {
                "Section 3": {
                    "search": {"value": postcode_search, "value_changed": True},
                    "select_NewAddress": {"value": ""},
                }
            },
            headers=post_headers,
            body=_FORM,
            check=False,
        )

        today_str = now.strftime("%Y-%m-%d")
        result = await run_lookup(
            http,
            _API_URL,
            sid,
            _SCHEDULE_LOOKUP_ID,
            {
                "Section 3": {
                    "select_NewAddress": {"value": uprn, "value_changed": True},
                    "search": {"value": postcode_search, "value_changed": True},
                    "serviceUPRN": {"value": uprn, "value_changed": True},
                    "formatted_search": {"value": postcode, "value_changed": True},
                    "chooseADate": {"value": today_str, "value_changed": True},
                    "currentDate": {"value": today_str, "value_changed": True},
                }
            },
            headers=post_headers,
            body=_FORM,
        )

        reply_rows = data_rows(result)
        if not reply_rows:
            return []  # the council lists nothing for this property

        collections: list[Collection] = []
        for row in reply_rows:
            date_str = row.get("binDate")
            bin_type = row.get("binTypeList")
            # 1900 is the placeholder date for a bin type with nothing scheduled.
            if date_str and bin_type and "1900" not in date_str:
                day = datetime.strptime(date_str, "%Y-%m-%d").date()
                collections.append(Collection(day, bin_type))

        return collections


SCRAPER = Angus()
