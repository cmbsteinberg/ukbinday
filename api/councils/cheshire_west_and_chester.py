"""Cheshire West and Chester: AchieveForms lookup keyed on the UPRN."""

from __future__ import annotations

from datetime import datetime

from api.councils._base import Address, Collection, Http, Meta, Scraper, UpstreamError
from api.councils._platforms.achieveforms import (
    first_row,
    init_session,
    rows,
    run_lookup,
)

_HOSTNAME = "my.cheshirewestandchester.gov.uk"
_FORM_URL = (
    f"https://{_HOSTNAME}/en/AchieveForms/"
    "?form_uri=sandbox-publish://AF-Process-0187a2f6-15cb-413a-8a3f-b6d14d63da57/"
    "AF-Stage-e18b38ff-be8a-45f4-ac14-f8821024f0c4/definition.json"
    "&redirectlink=/en&cancelRedirectLink=/en&consentMessage=yes"
)
_AUTH_URL = f"https://{_HOSTNAME}/authapi/isauthenticated"
_API_URL = f"https://{_HOSTNAME}/apibroker/runLookup"
_AUTH_LOOKUP_ID = "609b918c7dd6d"
_SERVICE_TYPES_LOOKUP_ID = "6101d1a29ba09"
_SCHEDULE_LOOKUP_ID = "6101d23110243"
_APP_NAME = "AchieveForms"
_HEADERS = {"user-agent": "Mozilla/5.0"}
_GENERIC_SERVICE_TYPES = frozenset({"Domestic", "Food", "Recycling", "Garden"})


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

        sid = await init_session(http, _FORM_URL, _AUTH_URL, _HOSTNAME, uri=_FORM_URL)

        auth_row = first_row(
            await run_lookup(http, _API_URL, sid, _AUTH_LOOKUP_ID, None, app_name=_APP_NAME)
        )
        if auth_row is None or "AuthenticateResponse" not in auth_row:
            raise UpstreamError("Cheshire West and Chester gave no AuthenticateResponse")

        form_values = {
            "Section 1": {
                "AuthenticateResponse": {
                    "name": "AuthenticateResponse",
                    "value": auth_row["AuthenticateResponse"],
                },
                "UPRN": {"name": "UPRN", "value": uprn},
            }
        }

        service_data = rows(
            await run_lookup(http, _API_URL, sid, _SERVICE_TYPES_LOOKUP_ID, form_values, app_name=_APP_NAME)
        )
        if not service_data:
            return []  # the council has no services for this property

        service_type_to_generic: dict[str, str] = {}
        for service in service_data.values():
            generic_service = service["service"].strip()
            if generic_service in _GENERIC_SERVICE_TYPES:
                service_type_to_generic[service["serviceType"]] = generic_service

        schedule_data = rows(
            await run_lookup(http, _API_URL, sid, _SCHEDULE_LOOKUP_ID, form_values, app_name=_APP_NAME)
        )

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
