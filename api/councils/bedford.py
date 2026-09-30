"""Bedford: a UPRN-keyed API returns scheduled residential bin collections."""

from __future__ import annotations

from datetime import datetime

from api.councils._base import Address, Collection, Http, Meta, Scraper, Transport

_API = "https://bbaz-as-prod-bartecapi.azurewebsites.net/api/bincollections/residential/getbyuprn"

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://www.bedford.gov.uk/",
    "Origin": "https://www.bedford.gov.uk",
}


class Bedford(Scraper):
    meta = Meta(
        title="Bedford Borough Council",
        url="https://bedford.gov.uk",
        lads=("E06000055",),
        cases={
            "Test_001": {"uprn": "100080009302"},
            "Test_003": {"uprn": "100080018481"},
            "Test_004": {"uprn": "100080023672"},
        },
    )
    requires = frozenset({"uprn"})
    headers = _HEADERS
    transport = Transport.CURL_CFFI

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        uprn = address.need("uprn").zfill(12)
        r = await http.get(f"{_API}/{uprn}")
        json_data = r.json().get("BinCollections", [])

        collections = []
        for day in json_data:
            for bin_data in day:
                bin_type = bin_data.get("BinType", "")
                job_start = bin_data.get("JobScheduledStart")
                if not job_start or not bin_type:
                    continue

                collections.append(
                    Collection(
                        datetime.strptime(job_start, "%Y-%m-%dT00:00:00").date(),
                        bin_type,
                    )
                )
        return collections


SCRAPER = Bedford()
