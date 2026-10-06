"""Mid Devon: submits the UPRN through AchieveForms and parses the lookup rows."""

from __future__ import annotations

import re
from datetime import datetime

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
from api.councils._platforms.achieveforms import (
    init_session,
    page_session_id,
    rows,
    run_lookup,
)

_HOSTNAME = "my.middevon.gov.uk"
_FORM_PAGE_URL = (
    f"https://{_HOSTNAME}/en/AchieveForms/"
    "?form_uri=sandbox-publish://AF-Process-2289dd06-9a12-4202-ba09-857fe756f6bd/"
    "AF-Stage-eb382015-001c-415d-beda-84f796dbb167/definition.json"
    "&redirectlink=%2Fen&cancelRedirectLink=%2Fen&consentMessage=yes"
)
_AUTH_URL = f"https://{_HOSTNAME}/authapi/isauthenticated"
_API_URL = f"https://{_HOSTNAME}/apibroker/runLookup"
_LOOKUP_ID = "642315aacb919"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9",
}


def _parse_api_rows(rows: dict[str, object]) -> list[Collection]:
    """Parse rows containing display dates and CollectionItems."""
    entries: list[Collection] = []
    for row in rows.values():
        if not isinstance(row, dict):
            continue
        date_str = row.get("display")
        items_value = row.get("CollectionItems") or ""
        items_str = items_value if isinstance(items_value, str) else ""
        if not isinstance(date_str, str) or not date_str:
            continue
        try:
            day = datetime.strptime(date_str, "%d-%b-%y").date()
        except ValueError:
            continue
        for part in re.split(r"\s+(?:and|&)\s+", items_str, flags=re.I):
            part = part.strip()
            if part:
                entries.append(Collection(day, part))
    return entries


def _parse_lookup_rows(rows: dict[str, object]) -> list[Collection]:
    """Parse lookup rows using the CollectionDay field as the type."""
    entries: list[Collection] = []
    for row in rows.values():
        if not isinstance(row, dict):
            continue
        date_str = row.get("display")
        if not isinstance(date_str, str) or not date_str:
            continue
        try:
            day = datetime.strptime(date_str, "%d-%b-%y").date()
        except ValueError:
            continue
        collection_day = row.get("CollectionDay", "")
        if not isinstance(collection_day, str):
            collection_day = ""
        entries.append(Collection(day, collection_day))
    return entries


class MidDevon(Scraper):
    meta = Meta(
        title="Mid Devon District Council",
        url="https://www.middevon.gov.uk",
        lads=("E07000042",),
        cases={
            "Bradninch": {"uprn": "100040359199"},
            "Bradninch - string": {"uprn": "100040359199"},
            "Cullompton": {"uprn": "100040354099"},
        },
    )
    requires = frozenset({"uprn"})
    headers = _HEADERS

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        uprn = address.need("uprn").strip()
        response = await http.get(_FORM_PAGE_URL, timeout=30)
        try:
            session_id = page_session_id(response.text)
        except UpstreamError:
            # No session id printed in the page: ask the auth API for one.
            session_id = await init_session(http, None, _AUTH_URL, _HOSTNAME, uri=_FORM_PAGE_URL)

        result = await run_lookup(
            http,
            _API_URL,
            session_id,
            _LOOKUP_ID,
            {
                "Section 1": {
                    "UPRN": {"name": "UPRN", "value": uprn},
                    "listAddress": {"name": "listAddress", "value": uprn},
                }
            },
        )
        lookup_rows = rows(result)
        if not lookup_rows:
            raise AddressNotFound("No collection data returned for this address.")
        first_row = next(iter(lookup_rows.values()))
        if not isinstance(first_row, dict):
            raise InputError("Council lookup returned unexpected data format.")

        if "display" in first_row and "CollectionItems" in first_row:
            entries = _parse_api_rows(lookup_rows)
            if entries:
                return entries
        return _parse_lookup_rows(lookup_rows)


SCRAPER = MidDevon()
