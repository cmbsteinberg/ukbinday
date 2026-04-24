from datetime import date, timedelta

import httpx

from api.compat.hacs import Collection

TITLE = "Hillingdon Council"
URL = "https://www.hillingdon.gov.uk"
TEST_CASES = {
    "Test_001": {"uprn": "100021488480", "postcode": "UB10 8PP"},
}

HEADERS = {
    "Content-Type": "application/json",
    "User-Agent": "Mozilla/5.0",
}

DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def _next_weekday(day_name: str) -> date:
    today = date.today()
    target = DAYS.index(day_name)
    current = today.weekday()
    delta = (target - current) % 7
    if delta == 0:
        delta = 7
    return today + timedelta(days=delta)


class Source:
    def __init__(self, uprn: str, postcode: str = ""):
        self._uprn = uprn

    async def fetch(self) -> list[Collection]:
        async with httpx.AsyncClient(follow_redirects=True) as client:
            resp = await client.post(
                "https://www.hillingdon.gov.uk/apiserver/ajaxlibrary",
                headers=HEADERS,
                json={
                    "jsonrpc": "2.0",
                    "id": "1",
                    "method": "Hillingdon.DatasourceQueries.alloy.GetBinCollectionDay",
                    "params": {"UPRN": self._uprn},
                },
            )
            data = resp.json()

        result = data.get("result", {})
        day_name = result.get("collectionDay", "")
        bin_types = result.get("collection", [])
        garden_date_str = result.get("gardenWasteCollectionDate", "")

        if not day_name or not bin_types:
            return []

        next_date = _next_weekday(day_name)
        collections = [Collection(next_date, t) for t in bin_types]

        if garden_date_str:
            from datetime import datetime

            try:
                gd = datetime.strptime(garden_date_str, "%d/%m/%Y").date()
                collections.append(Collection(gd, "Garden Waste"))
            except ValueError:
                pass

        return collections
