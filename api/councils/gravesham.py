"""Gravesham: an AchieveForms lookup, resolving postcode searches to a UPRN before fetching bin dates."""

from __future__ import annotations

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
    UpstreamError,
    match_address,
)
from api.councils._platforms.achieveforms import (
    first_row,
    init_session,
    rows,
    run_lookup,
)

_HOSTNAME = "my.gravesham.gov.uk"
_AUTH_URL = f"https://{_HOSTNAME}/authapi/isauthenticated"
_FORM_URI = (
    f"https://{_HOSTNAME}/en/AchieveForms/?form_uri=sandbox-publish://AF-Process-22218d5c-c6d6-492f-b627-c713771126be/"
    "AF-Stage-905e87c1-144b-4a72-8932-5518ddd3e618/definition.json"
    "&redirectlink=%2Fen&cancelRedirectLink=%2Fen&consentMessage=yes"
)
_API_URL = f"https://{_HOSTNAME}/apibroker/runLookup"
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

        sid = await init_session(http, None, _AUTH_URL, _HOSTNAME, uri=_FORM_URI)

        if user_uprn is None:
            addresses = rows(
                await run_lookup(
                    http,
                    _API_URL,
                    sid,
                    "58c855b298b88",
                    {"Section 1": {"postcode_search": {"value": postcode}}},
                )
            )
            if not addresses:
                raise InputError(f"No addresses found for postcode {postcode}")

            candidates = list(addresses.values())
            match = match_address(
                address,
                candidates,
                text=_candidate_text,
                uprn=lambda candidate: candidate.get("uprn"),
            )
            user_uprn = str(match["uprn"])

        token_row = first_row(await run_lookup(http, _API_URL, sid, "5ee8854759297", {"Section 1": {}}))
        if token_row is None or "tokenString" not in token_row:
            raise UpstreamError("Gravesham gave no tokenString")
        token_string = token_row["tokenString"]

        current_datetime = datetime.now()
        future_datetime = current_datetime + relativedelta(months=1)
        current_value = current_datetime.strftime("%Y-%m-%dT%H:%M:%S")
        future_value = future_datetime.strftime("%Y-%m-%dT%H:%M:%S")

        rows_data = rows(
            await run_lookup(
                http,
                _API_URL,
                sid,
                "5c8f869376376",
                {
                    "Check your bin day": {
                        "tokenString": {"value": token_string},
                        "UPRNForAPI": {"value": user_uprn},
                        "formatDateToday": {"value": current_value},
                        "formatDateTo": {"value": future_value},
                    }
                },
            )
        )

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
