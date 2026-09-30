"""Gravesham: an AchieveForms lookup, resolving postcode searches to a UPRN before fetching bin dates."""

from __future__ import annotations

import time
from collections.abc import Mapping
from datetime import datetime

from dateutil.relativedelta import relativedelta

from api.councils._base import (
    Address,
    Collection,
    Http,
    InputError,
    Meta,
    Scraper,
    match_address,
)

_SESSION_URL = (
    "https://my.gravesham.gov.uk/authapi/isauthenticated?uri=https%253A%252F%252Fmy.gravesham.gov.uk"
    "%252Fen%252FAchieveForms%252F%253Fform_uri%253Dsandbox-publish%253A%252F%252FAF-Process-"
    "22218d5c-c6d6-492f-b627-c713771126be%252FAF-Stage-905e87c1-144b-4a72-8932-5518ddd3e618"
    "%252Fdefinition.json%2526redirectlink%253D%25252Fen%2526cancelRedirectLink%253D%25252Fen"
    "%2526consentMessage%253Dyes&hostname=my.gravesham.gov.uk&withCredentials=true"
)
_API_URL = "https://my.gravesham.gov.uk/apibroker/runLookup"
_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json",
    "User-Agent": "Mozilla/5.0",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": "https://my.gravesham.gov.uk/fillform/?iframe_id=fillform-frame-1&db_id=",
}


def _candidate_text(candidate: Mapping[str, object]) -> str:
    house = candidate.get("house", "")
    return house if isinstance(house, str) else str(house)


class Gravesham(Scraper):
    meta = Meta(
        title="Gravesham",
        url="https://my.gravesham.gov.uk",
        lads=("E07000109",),
        cases={},
    )
    requires = frozenset()
    headers = _HEADERS

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        user_uprn = address.uprn
        postcode = address.postcode
        house_number = address.house_number

        if user_uprn is None and (postcode is None or house_number is None):
            raise InputError("Gravesham needs a UPRN or a postcode and house number")

        session_response = await http.get(_SESSION_URL)
        sid = session_response.json()["auth-session"]

        async def run_lookup(
            lookup_id: str,
            section_name: str,
            form_values: Mapping[str, object],
        ) -> object:
            params = {
                "id": lookup_id,
                "repeat_against": "",
                "noRetry": "false",
                "getOnlyTokens": "undefined",
                "log_id": "",
                "app_name": "AF-Renderer::Self",
                "_": str(int(time.time() * 1000)),
                "sid": sid,
            }
            payload = {"formValues": {section_name: form_values}}
            response = await http.post(_API_URL, json=payload, params=params)
            return response.json()["integration"]["transformed"]["rows_data"]

        if user_uprn is None:
            addresses = await run_lookup(
                "58c855b298b88",
                "Section 1",
                {"postcode_search": {"value": postcode}},
            )
            if not isinstance(addresses, dict) or not addresses:
                raise InputError(f"No addresses found for postcode {postcode}")

            candidates = list(addresses.values())
            match = match_address(
                address,
                candidates,
                text=_candidate_text,
                uprn=lambda candidate: candidate.get("uprn"),
            )
            user_uprn = str(match["uprn"])

        token_rows = await run_lookup("5ee8854759297", "Section 1", {})
        token_string = token_rows["0"]["tokenString"]

        current_datetime = datetime.now()
        future_datetime = current_datetime + relativedelta(months=1)
        current_value = current_datetime.strftime("%Y-%m-%dT%H:%M:%S")
        future_value = future_datetime.strftime("%Y-%m-%dT%H:%M:%S")

        rows_data = await run_lookup(
            "5c8f869376376",
            "Check your bin day",
            {
                "tokenString": {"value": token_string},
                "UPRNForAPI": {"value": user_uprn},
                "formatDateToday": {"value": current_value},
                "formatDateTo": {"value": future_value},
            },
        )
        if not isinstance(rows_data, dict):
            raise InputError("Invalid data returned from API")

        collections: list[Collection] = []
        for item in rows_data.values():
            if not isinstance(item, dict):
                continue
            name = item.get("Name")
            day = item.get("Date")
            if not name or not day:
                continue
            try:
                collection_date = datetime.strptime(day, "%Y-%m-%dT%H:%M:%S").date()
            except (TypeError, ValueError):
                continue

            for bin_type in name.split("Empty Bin "):
                if bin_type:
                    collections.append(Collection(collection_date, bin_type.strip()))

        return collections


SCRAPER = Gravesham()
