"""Leeds: fetches the next eight weeks of bin collections from its UPRN-based API."""

from __future__ import annotations

from datetime import datetime, timedelta

from api.councils._base import Address, Collection, Http, Meta, Scraper

_API_URL = "https://api.leeds.gov.uk/public/waste/v1/BinsDays"
_HEADERS = {
    "ocp-apim-subscription-key": "ad8dd80444fe45fcad376f82cf9a5ab4",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36",
}


class Leeds(Scraper):
    meta = Meta(
        title="Leeds",
        url="https://www.leeds.gov.uk/residents/bins-and-recycling/check-your-bin-day",
        lads=("E08000035",),
        cases={},
    )
    requires = frozenset({"uprn"})
    headers = _HEADERS

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        start_date = datetime.now()
        end_date = start_date + timedelta(weeks=8)
        response = await http.get(
            _API_URL,
            params={
                "uprn": address.need("uprn"),
                "startDate": start_date.strftime("%Y-%m-%d"),
                "endDate": end_date.strftime("%Y-%m-%d"),
            },
        )

        collections = response.json()
        result = []
        for collection in collections:
            collection_date = datetime.strptime(
                collection["date"], "%Y-%m-%dT%H:%M:%S"
            ).date()
            result.append(Collection(collection_date, collection["type"]))
        return result


SCRAPER = Leeds()
