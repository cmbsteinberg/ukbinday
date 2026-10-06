"""Sandwell: AchieveForms lookup requests keyed by UPRN for each waste stream."""

from __future__ import annotations

from datetime import date, datetime

from api.councils._base import Address, Collection, Http, Meta, Scraper, UpstreamError
from api.councils._platforms.achieveforms import init_session, rows, run_lookup

_HOSTNAME = "my.sandwell.gov.uk"
_AUTH_URL = f"https://{_HOSTNAME}/authapi/isauthenticated"
_FORM_URI = (
    f"https://{_HOSTNAME}/en/AchieveForms/?form_uri=sandbox-publish://AF-Process-ebaa26a2-393c-4a3c-84f5-e61564192a8a/"
    "AF-Stage-e4c2cb32-db55-4ff5-845c-8b27f87346c4/definition.json"
    "&redirectlink=/en&cancelRedirectLink=/en&consentMessage=yes"
)
_API_URL = f"https://{_HOSTNAME}/apibroker/runLookup"
_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json",
    "User-Agent": "Mozilla/5.0",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": f"https://{_HOSTNAME}/fillform/?iframe_id=fillform-frame-1&db_id=",
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

        sid = await init_session(http, None, _AUTH_URL, _HOSTNAME, uri=_FORM_URI)

        form_values = {
            "Property details": {
                "Uprn": {"value": uprn},
                "NextCollectionFromDate": {"value": datetime.today().strftime("%Y-%m-%d")},
            }
        }

        collections: list[Collection] = []
        for lookup_id, date_key, waste_type in _LOOKUPS:
            for row in rows(await run_lookup(http, _API_URL, sid, lookup_id, form_values)).values():
                day = row.get(date_key)
                if not day:
                    continue
                collections.append(Collection(_parse_date(day), waste_type))

        return collections


SCRAPER = Sandwell()
