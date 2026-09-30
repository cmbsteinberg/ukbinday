"""Cheshire West and Chester: AchieveForms lookup keyed on the UPRN."""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any

from api.councils._base import Address, Collection, Http, Meta, Response, Scraper

_SESSION_URL = (
    "https://my.cheshirewestandchester.gov.uk/en/AchieveForms/"
    "?form_uri=sandbox-publish://AF-Process-0187a2f6-15cb-413a-8a3f-b6d14d63da57/"
    "AF-Stage-e18b38ff-be8a-45f4-ac14-f8821024f0c4/definition.json"
    "&redirectlink=%2Fen&cancelRedirectLink=%2Fen&consentMessage=yes"
)
_AUTH_URL = (
    "https://my.cheshirewestandchester.gov.uk/authapi/isauthenticated"
    "?uri=https%3A%2F%2Fmy.cheshirewestandchester.gov.uk%2Fen%2FAchieveForms%2F"
    "%3Fform_uri%3Dsandbox-publish%3A%2F%2FAF-Process-0187a2f6-15cb-413a-8a3f-b6d14d63da57"
    "%2FAF-Stage-e18b38ff-be8a-45f4-ac14-f8821024f0c4%2Fdefinition.json"
    "%26redirectlink%3D%2Fen%26cancelRedirectLink%3D%2Fen%26consentMessage%3Dyes"
    "&hostname=my.cheshirewestandchester.gov.uk&withCredentials=true"
)
_AUTH_RESPONSE_URL = (
    "https://my.cheshirewestandchester.gov.uk/apibroker/runLookup"
    "?id=609b918c7dd6d&repeat_against=&noRetry=false&getOnlyTokens=undefined"
    "&log_id=&app_name=AchieveForms"
)
_SERVICE_TYPES_URL = (
    "https://my.cheshirewestandchester.gov.uk/apibroker/runLookup"
    "?id=6101d1a29ba09&repeat_against=&noRetry=false&getOnlyTokens=undefined"
    "&log_id=&app_name=AchieveForms"
)
_SCHEDULE_URL = (
    "https://my.cheshirewestandchester.gov.uk/apibroker/runLookup"
    "?id=6101d23110243&repeat_against=&noRetry=false&getOnlyTokens=undefined"
    "&log_id=&app_name=AchieveForms"
)
_HEADERS = {"user-agent": "Mozilla/5.0"}
_GENERIC_SERVICE_TYPES = frozenset({"Domestic", "Food", "Recycling", "Garden"})


def _achieve_forms_data(response: Response) -> dict[str, Any]:
    return response.json()["integration"]["transformed"]["rows_data"]


class CheshireWestAndChester(Scraper):
    meta = Meta(
        title="Cheshire West and Chester Council",
        url="https://www.cheshirewestandchester.gov.uk",
        lads=("E06000050",),
        cases={
            "Chester": {"uprn": "100010030086"},
            "Northwich": {"uprn": "10011715183"},
            "Hartford": {"uprn": "100010181592"},
        },
    )
    requires = frozenset({"uprn"})
    headers = _HEADERS

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        uprn = address.need("uprn")

        await http.get(_SESSION_URL)
        auth_request = await http.get(_AUTH_URL)
        session_key = auth_request.json()["auth-session"]

        url_nonce = str(time.time_ns() // 1_000_000)
        auth_response = await http.post(
            _AUTH_RESPONSE_URL + "&_" + url_nonce + "&sid=" + session_key,
        )
        authenticate_response_nonce = _achieve_forms_data(auth_response)["0"][
            "AuthenticateResponse"
        ]

        uprn_payload = {
            "formValues": {
                "Section 1": {
                    "AuthenticateResponse": {
                        "name": "AuthenticateResponse",
                        "value": authenticate_response_nonce,
                    },
                    "UPRN": {"name": "UPRN", "value": uprn},
                }
            }
        }

        service_response = await http.post(
            _SERVICE_TYPES_URL + "&_" + url_nonce + "&sid=" + session_key,
            json=uprn_payload,
        )
        service_data = _achieve_forms_data(service_response)
        if len(service_data) < 1:
            return []

        service_type_to_generic: dict[str, str] = {}
        for service in service_data.values():
            generic_service = service["service"].strip()
            if generic_service in _GENERIC_SERVICE_TYPES:
                service_type_to_generic[service["serviceType"]] = generic_service

        schedule_response = await http.post(
            _SCHEDULE_URL + "&_" + url_nonce + "&sid=" + session_key,
            json=uprn_payload,
        )
        schedule_data = _achieve_forms_data(schedule_response)
        if len(schedule_data) < 1:
            return []

        collections = []
        for collection in schedule_data.values():
            collection_date = datetime.strptime(
                collection["collectionDateTime"], "%Y-%m-%dT%H:%M:%S"
            ).date()
            collection_type = collection["serviceType"]
            if service_type_to_generic.get(collection_type) is not None:
                collections.append(Collection(collection_date, collection_type))

        return collections


SCRAPER = CheshireWestAndChester()
