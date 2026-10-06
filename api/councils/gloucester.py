"""Gloucester: AchieveForms lookups chain bin IDs to workflow tokens and next collection dates."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from api.councils._base import Address, Collection, Http, Meta, Scraper
from api.councils._platforms.achieveforms import first_row, init_session, run_lookup

HOST = "https://gloucester-self.achieveservice.com"
HOSTNAME = "gloucester-self.achieveservice.com"
AUTH_URL = f"{HOST}/authapi/isauthenticated"
FORM_URI = f"{HOST}/service/Bins___Check_your_bin_day"
API_URL = f"{HOST}/apibroker/runLookup"

BIN_CONFIG_LOOKUP_ID = "63f72ddc8ca25"
BIN_TYPES: dict[str, dict[str, str]] = {
    "Refuse": {
        "workflow_lookup_id": "63f731d2b50d7",
        "next_lookup_id": "63ca72c70c3b1",
        "label": "Household waste (black bin)",
    },
    "Recycling": {
        "workflow_lookup_id": "63f89f73018c0",
        "next_lookup_id": "63cfcf4756b5d",
        "label": "Recycling",
    },
    "Food": {
        "workflow_lookup_id": "63f8a11714712",
        "next_lookup_id": "63cfcf8ac7877",
        "label": "Food waste",
    },
    "Garden": {
        "workflow_lookup_id": "63f8a15776b5d",
        "next_lookup_id": "63cfcfc1c486c",
        "label": "Garden waste",
    },
}
SECTION = "Your waste collections"
HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json",
    "User-Agent": "Mozilla/5.0",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": f"{HOST}/fillform/?iframe_id=fillform-frame-1&db_id=",
}


class Gloucester(Scraper):
    meta = Meta(
        title="Gloucester City Council",
        url="https://www.gloucester.gov.uk",
        lads=("E07000081",),
        cases={
            "Test_001": {"uprn": "100120479507", "postcode": "GL2 0RR"},
        },
    )
    requires = frozenset({"uprn"})
    headers = HEADERS

    async def _lookup(
        self, http: Http, sid: str, lookup_id: str, fields: dict[str, dict[str, str]]
    ) -> dict[str, Any]:
        reply = await run_lookup(
            http, API_URL, sid, lookup_id, {SECTION: fields}, no_retry="true"
        )
        return first_row(reply) or {}

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        sid = await init_session(http, None, AUTH_URL, HOSTNAME, uri=FORM_URI)

        uprn = address.need("uprn")
        ids = await self._lookup(
            http, sid, BIN_CONFIG_LOOKUP_ID, {"binUprn": {"value": uprn}}
        )
        collections: list[Collection] = []

        for bin_type, config in BIN_TYPES.items():
            id_field = f"{bin_type}Id"
            bin_id = ids.get(id_field)
            if not bin_id:
                continue

            workflow = await self._lookup(
                http,
                sid,
                config["workflow_lookup_id"],
                {id_field: {"value": bin_id}},
            )
            token = workflow.get(f"{bin_type}1")
            if not token:
                continue

            next_collection = await self._lookup(
                http,
                sid,
                config["next_lookup_id"],
                {f"{bin_type}1": {"value": token}},
            )
            value = next_collection.get(f"Next{bin_type}1DateISO")
            if not value:
                continue

            try:
                day = datetime.strptime(value, "%Y-%m-%d").date()
            except ValueError:
                continue
            collections.append(Collection(date=day, type=config["label"]))

        return collections


SCRAPER = Gloucester()
