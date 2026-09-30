"""Aberdeen City: two AchieveForms lookups obtain a token, then fetch a UPRN's bin schedule."""

from __future__ import annotations

import datetime
import re
import time

from api.councils._base import (
    Address,
    AddressNotFound,
    Collection,
    Http,
    InputError,
    Meta,
    Scraper,
)

_LOOKUP_ID_GET_TOKEN = "583c08ffc47fe"
_LOOKUP_ID_GET_SCHEDULE = "5a3141caf4016"

_SESSION_URL = (
    "https://integration.aberdeencity.gov.uk/authapi/isauthenticated"
    "?uri=https%253A%252F%252Fintegration.aberdeencity.gov.uk%252Fservice"
    "%252Fbin_collection_calendar___view"
    "&hostname=integration.aberdeencity.gov.uk&withCredentials=true"
)
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

        auth_resp = await http.get(_SESSION_URL, timeout=30)
        try:
            sid = auth_resp.json()["auth-session"]
        except (ValueError, KeyError, TypeError) as err:
            raise InputError(f"Could not establish session with Aberdeen form: {err}") from err

        token_params = {
            "id": _LOOKUP_ID_GET_TOKEN,
            "repeat_against": "",
            "noRetry": "true",
            "getOnlyTokens": "undefined",
            "log_id": "",
            "app_name": "AF-Renderer::Self",
            "_": str(int(time.time() * 1000)),
            "sid": sid,
        }
        token_resp = await http.post(_API_URL, params=token_params, timeout=30)
        try:
            token_row = token_resp.json()["integration"]["transformed"]["rows_data"]["0"]
            token = token_row["token"]
        except (ValueError, KeyError, TypeError) as err:
            raise InputError(f"Aberdeen token request returned unexpected payload: {err}") from err

        today = datetime.date.today()
        payload = {
            "formValues": {
                "Section 1": {
                    "nauprn": {"value": uprn},
                    "token": {"value": token},
                    "mindate": {"value": today.strftime("%Y-%m-%d")},
                    "maxdate": {
                        "value": (today + datetime.timedelta(days=60)).strftime("%Y-%m-%d")
                    },
                }
            }
        }
        sched_params = dict(token_params)
        sched_params["id"] = _LOOKUP_ID_GET_SCHEDULE
        sched_params["_"] = str(int(time.time() * 1000))

        sched_resp = await http.post(
            _API_URL,
            params=sched_params,
            json=payload,
            timeout=30,
        )
        try:
            rows = sched_resp.json()["integration"]["transformed"]["rows_data"]["0"]
        except (ValueError, KeyError, TypeError) as err:
            raise InputError(f"Aberdeen schedule request returned unexpected payload: {err}") from err

        if not isinstance(rows, dict) or not rows:
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
