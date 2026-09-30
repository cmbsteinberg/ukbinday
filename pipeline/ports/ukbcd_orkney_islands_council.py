from datetime import datetime

import httpx

from api.compat.hacs import Collection  # type: ignore[attr-defined]

TITLE = "Orkney Islands"
DESCRIPTION = "Source for Orkney Islands Council bin collections."
URL = "https://www.orkney.gov.uk"
TEST_CASES = {
    "Palace Gardens, Birsay": {"uprn": "134017306"},
    "Gill Pier, Westray": {"uprn": "134004695"},
}

# The council's bin-collection widget (https://www.orkney.gov.uk/bin-collections)
# looks an address up by its UPRN ("addressId") and returns dated collections.
API_URL = "https://www.orkney.gov.uk/actions/_orkney/bin-collection/lookup-address"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36",
    "Accept": "application/json",
}


class Source:
    def __init__(self, uprn: str | int | None = None):
        self._uprn = str(uprn).strip() if uprn else None

    async def fetch(self) -> list[Collection]:
        if not self._uprn:
            raise ValueError("uprn is required")

        async with httpx.AsyncClient(follow_redirects=True, headers=HEADERS) as client:
            r = await client.get(
                API_URL, params={"addressId": self._uprn}, timeout=30
            )
            r.raise_for_status()
            data = r.json()

        if not data.get("success"):
            raise ValueError(data.get("error") or "Address not found")

        area = data.get("binCollectionArea") or {}
        config = data.get("binConfig") or {}

        entries: list[Collection] = []
        for key, items in area.items():
            if not isinstance(items, list):
                continue
            label = (config.get(key) or {}).get("label") or key.replace("_", " ").title()
            for item in items:
                try:
                    date = datetime.strptime(item["date"], "%Y-%m-%d").date()
                except (KeyError, ValueError, TypeError):
                    continue
                entries.append(Collection(date=date, t=label, icon=None))

        entries.sort(key=lambda c: c.date)
        return entries
