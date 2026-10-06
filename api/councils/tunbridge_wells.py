"""Tunbridge Wells: AchieveForms lookup keyed on the UPRN, returning upcoming collection dates."""

from __future__ import annotations

from datetime import datetime

from api.councils._base import Address, Collection, Http, Meta, Scraper, UpstreamError
from api.councils._platforms.achieveforms import init_session, rows, run_lookup

_HEADERS = {"user-agent": "Mozilla/5.0"}
_HOSTNAME = "mytwbc.tunbridgewells.gov.uk"
_AUTH_URL = f"https://{_HOSTNAME}/authapi/isauthenticated"
_FORM_URI = (
    f"https://{_HOSTNAME}/AchieveForms/?mode=fill&consentMessage=yes"
    "&form_uri=sandbox-publish://AF-Process-e01af4d4-eb0f-4cfe-a5ac-c47b63f017ed/"
    "AF-Stage-88caf66c-378f-4082-ad1d-07b7a850af38/definition.json&process=1"
    "&process_uri=sandbox-processes://AF-Process-e01af4d4-eb0f-4cfe-a5ac-c47b63f017ed"
    "&process_id=AF-Process-e01af4d4-eb0f-4cfe-a5ac-c47b63f017ed"
)
_LOOKUP_URL = f"https://{_HOSTNAME}/apibroker/runLookup"


class TunbridgeWells(Scraper):
    meta = Meta(
        title="Tunbridge Wells",
        url="https://tunbridgewells.gov.uk/",
        lads=("E07000116",),
        cases={
            "10090058289": {"uprn": "10090058289"},
            "100061204678": {"uprn": "100061204678"},
        },
    )
    requires = frozenset({"uprn"})
    headers = _HEADERS

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        uprn = address.need("uprn")
        sid = await init_session(http, None, _AUTH_URL, _HOSTNAME, uri=_FORM_URI)

        reply_rows = rows(
            await run_lookup(
                http,
                _LOOKUP_URL,
                sid,
                "6314720683f30",
                {
                    "Property": {
                        key: {"value": uprn}
                        for key in ("addressPicker", "propertyReference", "siteReference")
                    }
                },
            )
        )

        collections = []
        for item in reply_rows.values():
            try:
                day = datetime.strptime(item["nextDateUnformatted"], "%d/%m/%Y").date()
                bin_type = item["collectionType"]
            except (KeyError, TypeError, ValueError) as exc:
                raise UpstreamError(f"Tunbridge Wells returned an unexpected row: {str(item)[:200]}") from exc
            collections.append(Collection(day, bin_type))
        return collections


SCRAPER = TunbridgeWells()
