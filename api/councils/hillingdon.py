"""Hillingdon: a UPRN-keyed JSON request returns collection weekdays and garden dates."""

from __future__ import annotations

from datetime import date, datetime

from api.councils._base import (
    Address,
    Collection,
    Http,
    Meta,
    Scraper,
    UpstreamError,
    next_weekday,
)

_ENDPOINT = "https://www.hillingdon.gov.uk/apiserver/ajaxlibrary"
_DAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


def _next_weekday(day_name: str) -> date:
    try:
        day_number = _DAYS.index(day_name)
    except ValueError as exc:
        raise UpstreamError(f"Hillingdon returned an unknown collection day: {day_name!r}") from exc
    return next_weekday(day_number, include_today=False)


class Hillingdon(Scraper):
    meta = Meta(
        title="Hillingdon Council",
        url="https://www.hillingdon.gov.uk",
        lads=("E09000017",),
        cases={"Test_001": {"uprn": "100021488480", "postcode": "UB10 8PP"}},
    )
    requires = frozenset({"uprn"})
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0",
    }

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        response = await http.post(
            _ENDPOINT,
            json={
                "jsonrpc": "2.0",
                "id": "1",
                "method": "Hillingdon.DatasourceQueries.alloy.GetBinCollectionDay",
                "params": {"UPRN": address.need("uprn")},
            },
        )
        result = response.json().get("result", {})
        day_name = result.get("collectionDay", "")
        bin_types = result.get("collection", [])
        garden_date_str = result.get("gardenWasteCollectionDate", "")

        if not day_name or not bin_types:
            return []

        next_date = _next_weekday(day_name)
        collections = [Collection(next_date, bin_type) for bin_type in bin_types]

        if garden_date_str:
            try:
                garden_date = datetime.strptime(garden_date_str, "%d/%m/%Y").date()
                collections.append(Collection(garden_date, "Garden Waste"))
            except ValueError:
                pass

        return collections


SCRAPER = Hillingdon()
