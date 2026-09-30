"""Sandwell: AchieveForms lookup requests keyed by UPRN for each waste stream."""

from __future__ import annotations

import time
from datetime import date, datetime

from api.councils._base import Address, Collection, Http, Meta, Scraper, UpstreamError

_SESSION_URL = (
    "https://my.sandwell.gov.uk/authapi/isauthenticated?"
    "uri=https://my.sandwell.gov.uk/en/AchieveForms/?form_uri=sandbox-publish://AF-Process-ebaa26a2-393c-4a3c-84f5-e61564192a8a/AF-Stage-e4c2cb32-db55-4ff5-845c-8b27f87346c4/definition.json&redirectlink=/en&cancelRedirectLink=/en&consentMessage=yes"
)
_API_URL = "https://my.sandwell.gov.uk/apibroker/runLookup"
_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json",
    "User-Agent": "Mozilla/5.0",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": "https://my.sandwell.gov.uk/fillform/?iframe_id=fillform-frame-1&db_id=",
}
_LOOKUPS = (
    ("686294de50729", "DWDate", "Household Waste (Grey)"),
    ("68629dd642423", "MDRDate", "Recycling (Blue)"),
    ("6863a78a1dd8e", "FWDate", "Food Waste (Brown)"),
    ("686295a88a750", "GWDate", "Garden Waste (Green)"),
)


def _parse_date(value: str) -> date:
    try:
        return datetime.strptime(value, "%d/%m/%Y").date()
    except ValueError as exc:
        raise UpstreamError(f"Invalid date from Sandwell: {value}") from exc


class Sandwell(Scraper):
    meta = Meta(
        title="Sandwell Council",
        url="https://my.sandwell.gov.uk/",
        lads=("E08000028",),
        cases={
            "uprn_10008535856": {"uprn": "10008535856"},
            "uprn_10008535857": {"uprn": "10008535857"},
        },
    )
    requires = frozenset({"uprn"})
    headers = _HEADERS

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        uprn = address.need("uprn")

        session_response = await http.get(_SESSION_URL, timeout=30)
        session_data = session_response.json()
        sid = session_data.get("auth-session")
        if not sid:
            raise UpstreamError(f"Unexpected auth response (no auth-session): {session_data}")

        payload = {
            "formValues": {
                "Property details": {
                    "Uprn": {"value": uprn},
                    "NextCollectionFromDate": {
                        "value": datetime.today().strftime("%Y-%m-%d")
                    },
                }
            }
        }
        base_params = {
            "repeat_against": "",
            "noRetry": "false",
            "getOnlyTokens": "undefined",
            "log_id": "",
            "app_name": "AF-Renderer::Self",
            "sid": sid,
            "_": str(int(time.time() * 1000)),
        }

        collections: list[Collection] = []
        for lookup_id, date_key, waste_type in _LOOKUPS:
            response = await http.post(
                _API_URL,
                json=payload,
                params={"id": lookup_id, **base_params},
                timeout=30,
            )
            data = response.json()

            if isinstance(data, dict) and data.get("result") == "logout":
                raise UpstreamError("Sandwell returned logout (session rejected). Try again later or adjust headers.")

            transformed = (data.get("integration") or {}).get("transformed") or {}
            rows_data = transformed.get("rows_data")
            if not isinstance(rows_data, dict):
                continue

            for row in rows_data.values():
                day = row.get(date_key)
                if not day:
                    continue
                collections.append(Collection(_parse_date(day), waste_type))

        return collections


SCRAPER = Sandwell()
