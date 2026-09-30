"""Bristol: initialise the dynamic form, look up the UPRN, then retrieve collection dates."""

from __future__ import annotations

from datetime import datetime

from api.councils._base import Address, Collection, Http, Meta, Scraper

_HEADERS = {
    "Accept": "*/*",
    "Accept-Language": "en-GB,en;q=0.9",
    "Connection": "keep-alive",
    "Ocp-Apim-Subscription-Key": "47ffd667d69c4a858f92fc38dc24b150",
    "Ocp-Apim-Trace": "true",
    "Origin": "https://bristolcouncil.powerappsportals.com",
    "Referer": "https://bristolcouncil.powerappsportals.com/",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "cross-site",
    "Sec-GPC": "1",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/105.0.0.0 Safari/537.36",
}


class Bristol(Scraper):
    meta = Meta(
        title="Bristol City Council",
        url="https://bristol.gov.uk",
        lads=("E06000023",),
        cases={
            "Test_001": {"uprn": "107652"},
            "Test_002": {"uprn": "2987"},
            "Test_003": {"uprn": "17929"},
        },
    )
    requires = frozenset({"uprn"})
    headers = _HEADERS

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        uprn = address.need("uprn").zfill(12)

        await http.get(
            "https://bristolcouncil.powerappsportals.com/completedynamicformunauth/",
            headers=self.headers,
            params={"servicetypeid": "7dce896c-b3ba-ea11-a812-000d3a7f1cdc"},
        )

        await http.post(
            "https://bcprdapidyna002.azure-api.net/bcprdfundyna001-llpg/DetailedLLPG",
            headers=self.headers,
            json={"Uprn": "UPRN" + uprn},
        )

        response = await http.post(
            "https://bcprdapidyna002.azure-api.net/bcprdfundyna001-alloy/NextCollectionDates",
            headers=self.headers,
            json={"uprn": uprn},
        )
        data = response.json()["data"]

        collections = []
        for item in data:
            for collection in item["collection"]:
                for collection_date_key in ["nextCollectionDate", "lastCollectionDate"]:
                    date_string = collection[collection_date_key].split("T")[0]
                    collections.append(
                        Collection(
                            date=datetime.strptime(date_string, "%Y-%m-%d").date(),
                            type=item["containerName"],
                        )
                    )

        return collections


SCRAPER = Bristol()
