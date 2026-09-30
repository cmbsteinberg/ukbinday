"""Colchester: search LLPG addresses by postcode, then fetch the property's collection calendar."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from api.councils._base import (
    Address,
    Collection,
    Http,
    Meta,
    Scraper,
    match_address,
)

LLPG_API = "https://www.colchester.gov.uk/_api/new_llpgs"
CALENDAR_API = "https://new-llpg-app.azurewebsites.net/api/calendar"


def _candidate_text(candidate: dict[str, Any]) -> str:
    parts = (
        candidate.get("new_saon"),
        candidate.get("new_paon"),
        candidate.get("new_street"),
        candidate.get("new_name"),
    )
    return " ".join(str(part).strip() for part in parts if part)


def _parse_calendar(data: dict[str, Any]) -> list[Collection]:
    first_dates = data.get("DatesOfFirstCollectionDays", {})
    weeks = data.get("Weeks", [])
    entries: list[Collection] = []

    for day_name, first_date_str in first_dates.items():
        first_date = datetime.fromisoformat(first_date_str.split("T")[0]).date()
        week_bins: list[tuple[bool, list[str]]] = []
        for week in weeks:
            bins_for_day = week.get("Rows", {}).get(day_name, [])
            is_week_one = week.get("WeekOne", False)
            bin_names = [bin_data["Name"] for bin_data in bins_for_day]
            week_bins.append((is_week_one, bin_names))

        if not week_bins:
            continue

        cycle_len = len(week_bins)
        today = date.today()
        current = first_date
        for i in range(52):
            collection_date = current + timedelta(weeks=i)
            if collection_date < today - timedelta(days=1):
                continue
            if collection_date > today + timedelta(days=90):
                break
            week_idx = i % cycle_len
            _, bin_names = week_bins[week_idx]
            for bin_name in bin_names:
                entries.append(Collection(date=collection_date, type=bin_name))

    return entries


class Colchester(Scraper):
    meta = Meta(
        title="Colchester City Council",
        url="https://www.colchester.gov.uk",
        lads=("E07000071",),
        cases={
            "Test_001": {"postcode": "CO2 8UN", "house_number": "29"},
        },
    )
    requires = frozenset({"postcode"})

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        r = await http.get(
            LLPG_API,
            params={
                "$select": "new_llpgid,new_saon,new_paon,new_street,new_postcoide,new_name",
                "$filter": f"(new_postcoide eq '{address.need('postcode')}')",
            },
        )
        addresses = r.json().get("value", [])
        candidate = match_address(address, addresses, text=_candidate_text)
        llpg_id = candidate["new_llpgid"]

        r = await http.get(f"{CALENDAR_API}/{llpg_id}")
        return _parse_calendar(r.json())


SCRAPER = Colchester()
