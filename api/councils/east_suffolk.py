"""East Suffolk: AchieveForms with a Bartec token lookup, then a 90-day collections lookup by UPRN."""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta

from api.councils._base import Address, AddressNotFound, Collection, Http, Meta, Scraper
from api.councils._platforms.achieveforms import init_session, run_lookup

_BASE_URL = "https://my.eastsuffolk.gov.uk"
_API_URL = f"{_BASE_URL}/apibroker/runLookup"
_AUTH_LOOKUP_ID = "59e73f8bd860c"
_COLLECTIONS_LOOKUP_ID = "68f900a32e7a4"

# The API puts an emoji glyph in front of the label.
_LEADING_EMOJI = re.compile(r"^[^A-Za-z]+")


class EastSuffolk(Scraper):
    meta = Meta(
        title="East Suffolk Council",
        url="https://www.eastsuffolk.gov.uk",
        lads=("E07000244",),
        cases={
            "106 Mill Lane": {"uprn": "100091126543"},
            "82 Mill Lane": {"uprn": "100091126520"},
        },
    )
    requires = frozenset({"uprn"})
    headers = {"User-Agent": "Mozilla/5.0"}

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        uprn = address.need("uprn")
        sid = await init_session(
            http,
            f"{_BASE_URL}/service/Bin_collection_dates_finder",
            f"{_BASE_URL}/authapi/isauthenticated",
            "my.eastsuffolk.gov.uk",
        )
        auth_result = await run_lookup(
            http, _API_URL, sid, _AUTH_LOOKUP_ID, {"Details": {"bartecMode": {"value": "Live"}}}
        )
        auth_rows = auth_result.get("integration", {}).get("transformed", {}).get("rows_data")
        auth_token = ""
        if isinstance(auth_rows, dict):
            auth_token = auth_rows.get("0", {}).get("AuthenticateResponse", "")
        if not auth_token:
            raise AddressNotFound(f"East Suffolk does not know UPRN {uprn}")

        today = date.today()
        end_date = today + timedelta(days=90)
        result = await run_lookup(
            http,
            _API_URL,
            sid,
            _COLLECTIONS_LOOKUP_ID,
            {
                "Details": {
                    "bartecMode": {"value": "Live"},
                    "AuthenticateResponse": {"value": auth_token},
                    "finalUPRN": {"value": uprn},
                    "minimum_date": {"value": today.strftime("%Y-%m-%dT00:00:00")},
                    "maximum_date": {"value": end_date.strftime("%Y-%m-%dT00:00:00")},
                }
            },
        )
        rows = result.get("integration", {}).get("transformed", {}).get("rows_data")
        if not isinstance(rows, dict) or not rows:
            raise AddressNotFound(f"East Suffolk has no collections for UPRN {uprn}")

        collections = []
        for row in rows.values():
            text = row.get("CollectionDateFormatted", "").strip()
            if not text:
                continue
            try:
                day = datetime.strptime(text, "%d/%m/%Y").date()
            except ValueError:
                continue
            waste_type = _LEADING_EMOJI.sub("", row.get("CollectionTypeDescriptive", "")).strip()
            if not waste_type:
                waste_type = row.get("CollectionType", "").strip()
            if not waste_type:
                continue
            collections.append(Collection(day, waste_type))
        return collections


SCRAPER = EastSuffolk()
