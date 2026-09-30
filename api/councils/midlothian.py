"""Midlothian: an AchieveForms lookup using the property's UPRN and postcode."""

from __future__ import annotations

import datetime
import time

from api.councils._base import (
    Address,
    AddressNotFound,
    Collection,
    Http,
    InputError,
    Meta,
    Scraper,
)

_AUTH_URL = "https://my.midlothian.gov.uk/authapi/isauthenticated"
_DOMAIN_URL = "https://my.midlothian.gov.uk/apibroker/domain/my.midlothian.gov.uk"
_RUN_LOOKUP_URL = "https://my.midlothian.gov.uk/apibroker/runLookup"
_LOOKUP_ID = "69948bdca6012"
_NO_RETRY = "false"


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

        auth_response = await http.get(_AUTH_URL, timeout=30)
        try:
            auth_data = auth_response.json()
        except ValueError as err:
            raise InputError(f"Invalid response while creating session: {err}") from err

        sid = auth_data.get("auth-session")
        if not sid:
            raise InputError("Could not establish session with council form.")

        await http.get(
            _DOMAIN_URL,
            params={"_": time.time_ns() // 1_000_000, "sid": sid},
            timeout=30,
        )

        today = datetime.date.today()
        from_date = today.strftime("%Y-%m-%d")
        to_date = (today + datetime.timedelta(days=365)).strftime("%Y-%m-%d")
        payload = {
            "stopOnFailure": True,
            "usePHPIntegrations": True,
            "stage_id": "AF-Stage-a0bdbc4e-b9fc-46f0-bb0c-14a12cd927ed",
            "stage_name": "Stage 1",
            "formId": "AF-Form-033371a6-b0e4-4e16-a3b5-f68f592d8bf1",
            "formValues": {
                "Section 1": {
                    "postcode": {"value": postcode},
                    "UPRN": {"value": uprn},
                    "uprn": {"value": uprn},
                    "fromDate": {"value": from_date},
                    "toDate": {"value": to_date},
                }
            },
        }
        params = {
            "id": _LOOKUP_ID,
            "repeat_against": "",
            "noRetry": _NO_RETRY,
            "getOnlyTokens": "undefined",
            "log_id": "",
            "app_name": "AF-Renderer::Self",
            "_": time.time_ns() // 1_000_000,
            "sid": sid,
        }
        response = await http.post(_RUN_LOOKUP_URL, params=params, json=payload, timeout=30)
        try:
            data = response.json()
        except ValueError as err:
            raise InputError(f"Council lookup returned invalid JSON: {err}") from err

        if data.get("result") == "logout":
            raise InputError("Session expired while querying collection data.")

        rows = data.get("integration", {}).get("transformed", {}).get("rows_data", {})
        if not rows:
            raise AddressNotFound(f"No collection data returned for UPRN {uprn}.")

        collections: list[Collection] = []
        failed_rows: list[str] = []
        for row in rows.values():
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

        if rows and not collections:
            raise InputError(
                f"Failed to parse any collection dates from {len(rows)} rows. "
                f"API format may have changed. Failures: {failed_rows[:3]}"
            )

        return collections


SCRAPER = Midlothian()
