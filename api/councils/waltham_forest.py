"""Waltham Forest: an AchieveForms lookup keyed on the UPRN, returning service names and next collection dates."""

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

_HOSTNAME = "portal.walthamforest.gov.uk"
_AUTH_URL = f"https://{_HOSTNAME}/authapi/isauthenticated"
_FORM_URI = (
    f"https://{_HOSTNAME}/AchieveForms/?mode=fill&consentMessage=yes"
    "&form_uri=sandbox-publish://AF-Process-d62ccdd2-3de9-48eb-a229-8e20cbdd6393/"
    "AF-Stage-8bf39bf9-5391-4c24-857f-0dc2025c67f4/definition.json&process=1"
    "&process_uri=sandbox-processes://AF-Process-d62ccdd2-3de9-48eb-a229-8e20cbdd6393"
    "&process_id=AF-Process-d62ccdd2-3de9-48eb-a229-8e20cbdd6393"
)
_LOOKUP_URL = f"https://{_HOSTNAME}/apibroker/runLookup"
_HEADERS = {"user-agent": "Mozilla/5.0"}


class WalthamForest(Scraper):
    meta = Meta(
        title="Waltham Forest",
        url="https://walthamforest.gov.uk/",
        lads=("E09000031",),
        cases={
            "200001421821": {"uprn": "200001421821"},
            "100023583909": {"uprn": "100022551607"},
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
                "5e208cda0d0a0",
                {
                    "Property": {
                        key: {"value": uprn}
                        for key in (
                            "AccountSiteUprn",
                            "UPRNSearch",
                            "calcUPRN",
                            "customerUPRN",
                            "inputUPRN",
                        )
                    }
                },
            )
        )

        collections = []
        for item in reply_rows.values():
            try:
                bin_type = item["ServiceName"]
                next_date = item["NextCollectionDate"]
            except (KeyError, TypeError) as exc:
                raise UpstreamError(f"Waltham Forest returned an unexpected row: {str(item)[:200]}") from exc
            if next_date == " NaN ":
                continue
            try:
                day = parse_date(next_date)
            except ValueError:
                continue
            collections.append(Collection(day, bin_type))
        return collections


SCRAPER = WalthamForest()
