from datetime import date, datetime, timedelta

import httpx

from api.compat.hacs import Collection  # type: ignore[attr-defined]

TITLE = "Colchester City Council"
DESCRIPTION = "Source for colchester.gov.uk waste collection."
URL = "https://www.colchester.gov.uk"
TEST_CASES = {
    "Test_001": {"postcode": "CO2 8UN", "house_number": "29"},
}

LLPG_API = "https://www.colchester.gov.uk/_api/new_llpgs"
CALENDAR_API = "https://new-llpg-app.azurewebsites.net/api/calendar"

ICON_MAP = {
    "Paper/card": "mdi:newspaper-variant-outline",
    "Plastics": "mdi:recycle",
    "Food waste": "mdi:food-apple",
    "Black bags": "mdi:trash-can",
    "Glass": "mdi:bottle-wine",
    "Cans": "mdi:can",
    "Textiles": "mdi:tshirt-crew",
}

DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


class Source:
    def __init__(
        self,
        postcode: str,
        house_number: str = "",
        uprn: str | int | None = None,
    ):
        self._postcode = postcode
        self._house_number = house_number

    async def fetch(self) -> list[Collection]:
        async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as client:
            llpg_id = await self._resolve_llpg_id(client)
            r = await client.get(f"{CALENDAR_API}/{llpg_id}")
            r.raise_for_status()
            return _parse_calendar(r.json())

    async def _resolve_llpg_id(self, client: httpx.AsyncClient) -> str:
        r = await client.get(
            LLPG_API,
            params={
                "$select": "new_llpgid,new_saon,new_paon,new_street,new_postcoide,new_name",
                "$filter": f"(new_postcoide eq '{self._postcode}')",
            },
        )
        r.raise_for_status()
        addresses = r.json().get("value", [])
        if not addresses:
            raise ValueError(f"No addresses found for postcode {self._postcode}")

        target = self._house_number.strip().lower()
        for addr in addresses:
            paon = (addr.get("new_paon") or "").strip().lower()
            name = (addr.get("new_name") or "").strip().lower()
            if paon == target or name.startswith(target) or target.startswith(paon):
                return addr["new_llpgid"]

        raise ValueError(
            f"Address '{self._house_number}' not found for postcode {self._postcode}"
        )


def _parse_calendar(data: dict) -> list[Collection]:
    first_dates = data.get("DatesOfFirstCollectionDays", {})
    weeks = data.get("Weeks", [])
    entries: list[Collection] = []

    for day_name, first_date_str in first_dates.items():
        first_date = datetime.fromisoformat(first_date_str.split("T")[0]).date()
        week_bins: list[tuple[bool, list[str]]] = []
        for week in weeks:
            bins_for_day = week.get("Rows", {}).get(day_name, [])
            is_week_one = week.get("WeekOne", False)
            bin_names = [b["Name"] for b in bins_for_day]
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
                entries.append(
                    Collection(
                        date=collection_date,
                        t=bin_name,
                        icon=ICON_MAP.get(bin_name),
                    )
                )

    return sorted(entries, key=lambda c: c.date)
