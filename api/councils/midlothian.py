"""Midlothian: an AchieveForms lookup using the property's UPRN and postcode."""

from __future__ import annotations

import datetime

from api.councils._base import (
    Address,
    AddressNotFound,
    Collection,
    Http,
    InputError,
    Meta,
    Scraper,
)
from api.councils._platforms.achieveforms import init_session, rows, run_lookup

_HOSTNAME = "my.midlothian.gov.uk"
_AUTH_URL = f"https://{_HOSTNAME}/authapi/isauthenticated"
_DOMAIN_URL = f"https://{_HOSTNAME}/apibroker/domain/{_HOSTNAME}"
_RUN_LOOKUP_URL = f"https://{_HOSTNAME}/apibroker/runLookup"
_LOOKUP_ID = "69948bdca6012"
_FORM = {
    "stopOnFailure": True,
    "usePHPIntegrations": True,
    "stage_id": "AF-Stage-a0bdbc4e-b9fc-46f0-bb0c-14a12cd927ed",
    "stage_name": "Stage 1",
    "formId": "AF-Form-033371a6-b0e4-4e16-a3b5-f68f592d8bf1",
}


class Midlothian(Scraper):
    meta = Meta(
        title="Midlothian Council",
        url="https://my.midlothian.gov.uk/",
        lads=("S12000019",),
        cases={"Test1": {"uprn": "120001401", "postcode": "EH26 8AG"}},
    )
    requires = frozenset({"uprn", "postcode"})

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        uprn = address.need("uprn")
        postcode = address.need("postcode")

        sid = await init_session(
            http, None, _AUTH_URL, _HOSTNAME, uri=f"https://{_HOSTNAME}/", auth_test_url=_DOMAIN_URL
        )

        today = datetime.date.today()
        from_date = today.strftime("%Y-%m-%d")
        to_date = (today + datetime.timedelta(days=365)).strftime("%Y-%m-%d")
        lookup_rows = rows(
            await run_lookup(
                http,
                _RUN_LOOKUP_URL,
                sid,
                _LOOKUP_ID,
                {
                    "Section 1": {
                        "postcode": {"value": postcode},
                        "UPRN": {"value": uprn},
                        "uprn": {"value": uprn},
                        "fromDate": {"value": from_date},
                        "toDate": {"value": to_date},
                    }
                },
                body=_FORM,
            )
        )
        if not lookup_rows:
            raise AddressNotFound(f"No collection data returned for UPRN {uprn}.")

        collections: list[Collection] = []
        failed_rows: list[str] = []
        for row in lookup_rows.values():
            date_str = row.get("Date") or row.get("date")
            try:
                collection_date = datetime.datetime.strptime(
                    date_str, "%d/%m/%Y %H:%M:%S"
                ).date()
            except (ValueError, TypeError, AttributeError) as err:
                failed_rows.append(f"Date='{date_str}': {type(err).__name__}")
                continue

            waste_type = row.get("Service") or row.get("service")
            collections.append(Collection(collection_date, waste_type))

        if not collections:
            raise InputError(
                f"Failed to parse any collection dates from {len(lookup_rows)} rows. "
                f"API format may have changed. Failures: {failed_rows[:3]}"
            )

        return collections


SCRAPER = Midlothian()
