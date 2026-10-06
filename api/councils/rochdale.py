"""Rochdale: an AchieveForms lookup retrieves a Bartec token, then the annual bin calendar."""

from __future__ import annotations

from datetime import datetime, timedelta

from api.councils._base import (
    Address,
    Collection,
    Http,
    InputError,
    Meta,
    Scraper,
)
from api.councils._platforms.achieveforms import first_row, init_session, run_lookup

_HOSTNAME = "rochdale-self.achieveservice.com"
_BASE_URL = f"https://{_HOSTNAME}"
_API_URL = f"{_BASE_URL}/apibroker/runLookup"
_FORM = {"formId": "AF-Form-d7812e2d-2876-47c2-9802-8a4a3b1a2264"}
_REFERER = f"{_BASE_URL}/service/Bins___view_your_waste_collection_calendar"


class Rochdale(Scraper):
    meta = Meta(
        title="Rochdale Borough Council",
        url="https://www.rochdale.gov.uk",
        lads=("E08000005",),
        cases={
            "Test_001": {"uprn": "10094359340"},
            "Test_002": {"uprn": "23030658"},
            "Test_003": {"uprn": "23011384"},
        },
    )
    requires = frozenset({"uprn"})
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": _REFERER,
    }

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        uprn = address.need("uprn")

        sid = await init_session(
            http,
            None,
            f"{_BASE_URL}/authapi/isauthenticated",
            _HOSTNAME,
            uri=_REFERER,
            domain_url=f"{_BASE_URL}/apibroker/domain/{_HOSTNAME}",
        )

        token_row = first_row(
            await run_lookup(
                http,
                _API_URL,
                sid,
                "6846c784a46b5",
                {"Location details": {"propertyUPRN": {"value": uprn}}},
                body=_FORM,
            )
        )
        if token_row is None or "bartecToken" not in token_row:
            raise InputError(f"Rochdale API: Failed to retrieve bartecToken for UPRN {uprn}.")

        now = datetime.now()
        min_date = now.strftime("%Y-%m-%dT00:00:00")
        max_date = (now + timedelta(days=365)).strftime("%Y-%m-%dT23:59:59")
        row = first_row(
            await run_lookup(
                http,
                _API_URL,
                sid,
                "68b58a1364572",
                {
                    "Location details": {
                        "propertyUPRN": {"value": uprn},
                        "bartecToken": {"value": token_row["bartecToken"]},
                        "dateAnnualMinimum": {"value": min_date},
                        "dateAnnualMaximum": {"value": max_date},
                    }
                },
                no_retry="true",
                body=_FORM,
            )
        )
        if not row or "bartecAnnualBin1Type" not in row:
            raise InputError("Rochdale API: Failed to fetch calendar data or missing required fields.")

        collections: list[Collection] = []
        for index in range(1, 17):
            bin_type = row.get(f"bartecAnnualBin{index}Type")
            day = row.get(f"bartecAnnualBin{index}Day")
            month = row.get(f"bartecAnnualBin{index}Month")

            if bin_type and day and month:
                date_string = f"{day} {month} {now.year}"
                collection_date = datetime.strptime(date_string, "%d %B %Y").date()
                if collection_date < now.date() - timedelta(days=31):
                    collection_date = collection_date.replace(year=now.year + 1)
                collections.append(Collection(collection_date, bin_type))

        return collections


SCRAPER = Rochdale()
