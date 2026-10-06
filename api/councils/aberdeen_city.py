"""Aberdeen City: two AchieveForms lookups obtain a token, then fetch a UPRN's bin schedule."""

from __future__ import annotations

import datetime
import re

from api.councils._base import (
    Address,
    AddressNotFound,
    Collection,
    Http,
    InputError,
    Meta,
    Scraper,
    UpstreamError,
)
from api.councils._platforms.achieveforms import first_row, init_session, run_lookup

_LOOKUP_ID_GET_TOKEN = "583c08ffc47fe"
_LOOKUP_ID_GET_SCHEDULE = "5a3141caf4016"

_HOSTNAME = "integration.aberdeencity.gov.uk"
_AUTH_URL = f"https://{_HOSTNAME}/authapi/isauthenticated"
_FORM_URL = f"https://{_HOSTNAME}/service/bin_collection_calendar___view"
_API_URL = "https://integration.aberdeencity.gov.uk/apibroker/runLookup"

_DATE_KEY_RE = re.compile(r"^(.*?)Date\d+$")
_COUNT_KEY_RE = re.compile(r"^Count")

_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json",
    "User-Agent": "Mozilla/5.0",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": (
        "https://integration.aberdeencity.gov.uk/fillform/"
        "?iframe_id=fillform-frame-1&db_id="
    ),
}


def _split_camel(name: str) -> str:
    """Split Pascal-case waste-type identifiers into display labels."""
    return re.sub(r"(?<!^)(?=[A-Z])", " ", name).strip()


class AberdeenCity(Scraper):
    meta = Meta(
        title="Aberdeen City Council",
        url="https://www.aberdeencity.gov.uk/",
        lads=("S12000033",),
        cases={"179 Skene Street, AB10 1QN": {"uprn": "9051064786"}},
    )
    requires = frozenset({"uprn"})
    headers = _HEADERS

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        uprn = address.need("uprn")

        sid = await init_session(http, None, _AUTH_URL, _HOSTNAME, uri=_FORM_URL)

        token_row = first_row(
            await run_lookup(http, _API_URL, sid, _LOOKUP_ID_GET_TOKEN, None, no_retry="true")
        )
        if token_row is None or "token" not in token_row:
            raise UpstreamError("Aberdeen token request returned no token")
        token = token_row["token"]

        today = datetime.date.today()
        form_values = {
            "Section 1": {
                "nauprn": {"value": uprn},
                "token": {"value": token},
                "mindate": {"value": today.strftime("%Y-%m-%d")},
                "maxdate": {"value": (today + datetime.timedelta(days=60)).strftime("%Y-%m-%d")},
            }
        }
        rows = first_row(
            await run_lookup(http, _API_URL, sid, _LOOKUP_ID_GET_SCHEDULE, form_values, no_retry="true")
        )

        if not rows:
            raise AddressNotFound("No collection data returned for this UPRN.")

        has_date_keys = any(_DATE_KEY_RE.match(key) for key in rows)
        if not has_date_keys:
            raise AddressNotFound(
                "No collections found for this UPRN. Check the number is "
                "correct and that the property is within the City of Aberdeen."
            )

        collections: list[Collection] = []
        for key, value in rows.items():
            if _COUNT_KEY_RE.match(key):
                continue
            match = _DATE_KEY_RE.match(key)
            if not match or not value:
                continue
            bin_type = _split_camel(match.group(1))
            try:
                collection_date = datetime.datetime.strptime(value, "%A %d %B %Y").date()
            except (ValueError, TypeError):
                continue
            collections.append(Collection(collection_date, bin_type))

        if not collections:
            raise InputError(
                f"Aberdeen returned {len(rows)} rows including date keys but "
                "none parsed. The API format may have changed."
            )

        return collections


SCRAPER = AberdeenCity()
