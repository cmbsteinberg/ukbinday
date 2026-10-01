"""Watford: resolve a property through AchieveForms, then fetch its bin collections."""

from __future__ import annotations

import re
import time
from collections.abc import Mapping
from datetime import datetime
from html import unescape

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

_BASE_URL = "https://watfordbc-self.achieveservice.com"
_INITIAL_URL = f"{_BASE_URL}/en/service/Bin_Collections?accept=yes&consentMessageIds[]=9"
_API_URL = f"{_BASE_URL}/apibroker/runLookup"

_LOOKUP_ADDRESS_POINT = "5e57d2f638e6d"
_LOOKUP_NEXT_COLLECTIONS = "5e79edf15b2ec"
_LOOKUP_CALENDAR = "6750598d8b177"
_FORM_ID = "AF-Form-a139d516-46fc-4e1d-a94e-5e072681bcf0"
_REQUEST_TIMEOUT = 30


def _extract_collections(html_text: str) -> list[Collection]:
    html_text = unescape(html_text)
    items = re.findall(r'<li class="binItem">(.*?)</li>', html_text, flags=re.DOTALL)
    entries = []

    for item in items:
        title_match = re.search(r"<h3>(.*?)</h3>", item, flags=re.DOTALL)
        date_match = re.search(r"(\d{2}/\d{2}/\d{4})", item)
        if not title_match or not date_match:
            continue

        waste_type = re.sub(r"\s+", " ", unescape(title_match.group(1))).strip()
        day = datetime.strptime(date_match.group(1), "%d/%m/%Y").date()
        entries.append(Collection(day, waste_type))

    return entries


class Watford(Scraper):
    meta = Meta(
        title="Watford Borough Council",
        url="https://www.watford.gov.uk/",
        lads=("E07000103",),
        cases={
            "1 Coningsby Drive, Watford": {"uprn": "100080932722"},
        },
    )
    requires = frozenset()

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        uprn = address.uprn
        address_token = uprn or address.label
        if address_token is None:
            raise InputError("Watford needs a UPRN or an address token")

        uprn_value = str(uprn or address_token).lstrip("0")

        r = await http.get(_INITIAL_URL, timeout=_REQUEST_TIMEOUT)
        match = re.search(r'"auth-session":"([^"]+)"', r.text)
        if not match:
            raise UpstreamError("Failed to obtain Watford auth session")
        sid = match.group(1)

        async def run_lookup(lookup_id: str, form_values: Mapping[str, object]) -> dict:
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
            payload = {"formId": _FORM_ID, "formValues": form_values}
            response = await http.post(
                _API_URL,
                params=params,
                json=payload,
                timeout=_REQUEST_TIMEOUT,
            )
            data = response.json()
            transformed = data.get("integration", {}).get("transformed", {})
            if data.get("status") == "error" or transformed.get("error"):
                raise InputError(
                    f"Watford lookup {lookup_id} failed: "
                    f"{data.get('error') or transformed.get('error') or data.get('data')}"
                )
            return transformed

        transformed = await run_lookup(
            _LOOKUP_ADDRESS_POINT,
            {
                "Address": {
                    "echoUprn": {"value": uprn_value},
                    "address": {"value": str(address_token)},
                }
            },
        )
        row = transformed.get("rows_data", {}).get("0", {})
        echo_address_point = row.get("echoAddressPoint")
        if not echo_address_point:
            raise AddressNotFound("Watford could not resolve this address")

        form_values = {
            "Address": {
                "address": {"value": str(address_token)},
                "echoUprn": {"value": uprn_value},
                "echoAddressPoint": {"value": str(echo_address_point)},
            }
        }
        collections_data = await run_lookup(_LOOKUP_NEXT_COLLECTIONS, form_values)
        row = collections_data.get("rows_data", {}).get("0", {})
        entries = _extract_collections(row.get("dispHTML", ""))
        if entries:
            return entries

        if row.get("lastCollection") == "NaN-aN-aN":
            calendar_data = await run_lookup(_LOOKUP_CALENDAR, form_values)
            calendar = calendar_data.get("rows_data", {}).get("0", {}).get("calendar")
            raise InputError(
                "Watford did not return collection data for this property token "
                f"(calendar: {calendar or 'unknown'})."
            )

        raise InputError("Watford returned an unexpected response for this property token.")


SCRAPER = Watford()
