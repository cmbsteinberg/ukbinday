"""Mid Devon: submits the UPRN through AchieveForms and parses the lookup rows."""

from __future__ import annotations

import re
import time
from datetime import datetime

from api.councils._base import (
    Address,
    AddressNotFound,
    Collection,
    Http,
    InputError,
    Meta,
    Scraper,
)

_FORM_PAGE_URL = (
    "https://my.middevon.gov.uk/en/AchieveForms/"
    "?form_uri=sandbox-publish://AF-Process-2289dd06-9a12-4202-ba09-857fe756f6bd/"
    "AF-Stage-eb382015-001c-415d-beda-84f796dbb167/definition.json"
    "&redirectlink=%2Fen&cancelRedirectLink=%2Fen&consentMessage=yes"
)
_AUTH_URL = (
    "https://my.middevon.gov.uk/authapi/isauthenticated"
    "?uri=https%253A%252F%252Fmy.middevon.gov.uk%252Fen%252FAchieveForms%252F"
    "%253Fform_uri%253Dsandbox-publish%253A%252F%252FAF-Process-2289dd06-9a12-4202-ba09-857fe756f6bd%252F"
    "AF-Stage-eb382015-001c-415d-beda-84f796dbb167%252Fdefinition.json"
    "%2526redirectlink%253D%25252Fen%2526cancelRedirectLink%253D%25252Fen%2526consentMessage%253Dyes"
    "&hostname=my.middevon.gov.uk&withCredentials=true"
)
_RUN_LOOKUP_BASE = (
    "https://my.middevon.gov.uk/apibroker/runLookup"
    "?id=642315aacb919&repeat_against=&noRetry=false&getOnlyTokens=undefined"
    "&log_id=&app_name=AF-Renderer::Self"
)
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9",
}


def _extract_auth_session(html: str) -> str | None:
    """Extract the auth-session token from the form page."""
    match = re.search(r'["\']auth-session["\']\s*:\s*["\']([^"\']+)["\']', html)
    return match.group(1) if match else None


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
        session_id = _extract_auth_session(response.text)
        if not session_id:
            auth = await http.get(_AUTH_URL)
            auth_data = auth.json()
            if isinstance(auth_data, dict):
                token = auth_data.get("auth-session")
                session_id = token if isinstance(token, str) else None
        if not session_id:
            raise InputError("Could not establish session with council form.")

        rows = await self._fetch_lookup_rows(http, session_id, uprn)
        rows = await self._fetch_lookup_rows(http, session_id, uprn)
        if not rows:
            raise AddressNotFound("No collection data returned for this address.")
        first_row = next(iter(rows.values()))
        if not isinstance(first_row, dict):
            raise InputError("Council lookup returned unexpected data format.")

        if "display" in first_row and "CollectionItems" in first_row:
            entries = _parse_api_rows(rows)
            if entries:
                return entries
        return _parse_lookup_rows(rows)

    async def _fetch_lookup_rows(
        self, http: Http, session_id: str, uprn: str
    ) -> dict[str, object]:
        """Submit the UPRN and return the council's lookup rows."""
        now = time.time_ns() // 1_000_000
        lookup_url = f"{_RUN_LOOKUP_BASE}&_={now}&sid={session_id}"
        payload = {
            "formValues": {
                "Section 1": {
                    "UPRN": {"name": "UPRN", "value": uprn},
                    "listAddress": {"name": "listAddress", "value": uprn},
                }
            }
        }
        response = await http.post(lookup_url, json=payload, timeout=30)
        try:
            data = response.json()
        except ValueError as exc:
            raise InputError(f"Council lookup returned invalid response: {exc}") from exc

        if not isinstance(data, dict):
            raise InputError("Council lookup returned invalid response.")
        integration = data.get("integration")
        transformed = integration.get("transformed") if isinstance(integration, dict) else None
        rows_value = transformed.get("rows_data") if isinstance(transformed, dict) else None
        rows = rows_value or {}
        if not isinstance(rows, dict):
            raise InputError("Council lookup returned invalid response.")
        if not rows:
            raise AddressNotFound("No collection data returned for this address.")
        return rows


SCRAPER = MidDevon()
