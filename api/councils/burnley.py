"""Burnley: AchieveForms lookup keyed on the UPRN, returning the next collection dates."""

from __future__ import annotations

from api.councils._base import (
    Address,
    Collection,
    Http,
    Meta,
    Scraper,
    UpstreamError,
    parse_date,
)
from api.councils._platforms.achieveforms import init_session, rows, run_lookup

_HOSTNAME = "your.burnley.gov.uk"
_BASE = f"https://{_HOSTNAME}"
_FORM_URI = (
    f"{_BASE}/en/AchieveForms/?form_uri=sandbox-publish://AF-Process-b41dcd03-9a98-41be-93ba-6c172ba9f80c/"
    "AF-Stage-edb97458-fc4d-4316-b6e0-85598ec7fce8/definition.json"
    "&redirectlink=%2Fen&cancelRedirectLink=%2Fen&consentMessage=yes"
)


class Burnley(Scraper):
    meta = Meta(
        title="Burnley Council",
        url="https://burnley.gov.uk",
        lads=("E07000117",),
        cases={
            "Test_001": {"uprn": "100010341681"},
            "Test_002": {"uprn": "100010358864"},
            "Test_003": {"uprn": "100010357864"},
        },
    )
    requires = frozenset({"uprn"})
    headers = {"user-agent": "Mozilla/5.0"}

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        uprn = address.need("uprn").zfill(12)

        sid = await init_session(
            http,
            None,
            f"{_BASE}/authapi/isauthenticated",
            _HOSTNAME,
            uri=_FORM_URI,
            domain_url=f"{_BASE}/apibroker/domain/{_HOSTNAME}",
        )
        result = await run_lookup(
            http,
            f"{_BASE}/apibroker/runLookup",
            sid,
            "607fe757df87c",
            {"Section 1": {"case_uprn1": {"value": uprn}}},
        )

        collections = []
        for row in rows(result).values():
            try:
                waste, day_text = row["display"].split(" - ")
            except (KeyError, ValueError, AttributeError) as exc:
                raise UpstreamError(f"Burnley returned an unexpected collection row: {str(row)[:200]}") from exc
            collections.append(Collection(parse_date(day_text), waste))
        return collections


SCRAPER = Burnley()
