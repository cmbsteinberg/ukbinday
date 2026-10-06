"""East Cambridgeshire: AchieveForms lookup by UPRN, returning scheduled collections."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from api.councils._base import (
    Address,
    AddressNotFound,
    Collection,
    Http,
    Meta,
    Scraper,
    UpstreamError,
)
from api.councils._platforms.achieveforms import first_row, page_session_id, run_lookup

_HOSTNAME = "eastcambs-self.achieveservice.com"
_PROCESS_ID = "2c7575a6-0139-4555-9d8a-ab504a44d989"
_STAGE_ID = "94ee5097-94db-474d-bc7a-d1796e3ab83a"
_INITIAL_URL = f"https://{_HOSTNAME}/AchieveForms/"
_AUTH_LOOKUP_ID = "69d8f92eea3cf"
_COLLECTIONS_LOOKUP_ID = "6784e74793b68"
_API_URL = f"https://{_HOSTNAME}/apibroker/runLookup"
_APP_NAME = "AchieveForms"


class EastCambridgeshire(Scraper):
    meta = Meta(
        title="East Cambridgeshire District Council",
        url="https://www.eastcambs.gov.uk",
        lads=("E07000009",),
        cases={
            "14 Meadow Way Ely": {"uprn": "10002601730"},
            "20 Forehill Ely": {"uprn": "10002597181"},
        },
    )
    requires = frozenset({"uprn"})
    headers = {"user-agent": "Mozilla/5.0"}

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        r = await http.get(
            _INITIAL_URL,
            params={
                "mode": "fill",
                "consentMessage": "yes",
                "form_uri": f"sandbox-publish://AF-Process-{_PROCESS_ID}/AF-Stage-{_STAGE_ID}/definition.json",
                "process": "1",
                "process_uri": f"sandbox-processes://AF-Process-{_PROCESS_ID}",
                "process_id": f"AF-Process-{_PROCESS_ID}",
            },
            timeout=30,
        )

        sid = page_session_id(r.text, who="the East Cambs service page")

        auth_row = first_row(
            await run_lookup(
                http, _API_URL, sid, _AUTH_LOOKUP_ID, {"Section 1": {}}, app_name=_APP_NAME
            )
        )
        if auth_row is None or "AuthenticateResponse" not in auth_row:
            raise UpstreamError("East Cambridgeshire gave no AuthenticateResponse")

        today = date.today()
        service_start = date(2026, 6, 1)
        start_date = max(today, service_start)
        end_date = today + timedelta(days=90)

        uprn = address.need("uprn")
        col_data = await run_lookup(
            http,
            _API_URL,
            sid,
            _COLLECTIONS_LOOKUP_ID,
            {
                "Section 1": {
                    "AuthenticateResponse": {"value": auth_row["AuthenticateResponse"]},
                    "selected_uprn": {"value": uprn},
                    "MinimumDateForNextDates": {"value": start_date.strftime("%Y-%m-%d")},
                    "MaximumDateFormattedNext": {"value": end_date.strftime("%Y-%m-%d")},
                }
            },
            app_name=_APP_NAME,
        )

        # This lookup answers a dropdown (`select_data`: label "<bin> - dd/mm/yyyy"), not rows_data.
        transformed = (col_data.get("integration") or {}).get("transformed")
        if not isinstance(transformed, dict):
            raise UpstreamError(f"East Cambridgeshire reply has no integration.transformed: {str(col_data)[:200]}")
        select_data = transformed.get("select_data") or []
        if not select_data:
            raise AddressNotFound(f"East Cambridgeshire has no collections for UPRN {uprn}")

        collections = []
        for item in select_data:
            label = item.get("label", "")
            parts = label.rsplit(" - ", 1)
            if len(parts) != 2:
                continue
            bin_type, date_str = parts
            try:
                collection_date = datetime.strptime(date_str, "%d/%m/%Y").date()
            except ValueError:
                continue
            collections.append(Collection(collection_date, bin_type.strip()))

        return collections


SCRAPER = EastCambridgeshire()
