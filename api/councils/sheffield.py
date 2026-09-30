"""Sheffield: looks up collection records from the waste-services API by UPRN."""

from __future__ import annotations

from dateutil import parser

from api.councils._base import Address, Collection, Http, InputError, Meta, Scraper

_API_URL = "https://wasteservices.sheffield.gov.uk/"


class Sheffield(Scraper):
    meta = Meta(
        title="Sheffield City Council",
        url="https://sheffield.gov.uk/",
        lads=("E08000019",),
        cases={
            "test001": {"uprn": "100050938234"},
            "test002": {"uprn": "100050961380"},
            "test003": {"uprn": "100050920796"},
        },
    )
    requires = frozenset({"uprn"})

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        response = await http.post(
            f"{_API_URL}api/getCalendarData",
            json={"councilId": "1", "uprn": address.need("uprn")},
        )
        json_doc = response.json()

        if "data" not in json_doc:
            raise InputError("The returned API data does not contain expected data element")
        if "message" in json_doc and json_doc["message"] != "OK":
            raise InputError(f"API advised error: {json_doc['message']}")

        collections = []
        for data_item in json_doc["data"]:
            if "records" not in data_item:
                continue
            for record in data_item["records"]:
                collection_date = parser.parse(record["actual_scheduled_date"]).date()
                collections.append(Collection(collection_date, record["service"]))
        return collections


SCRAPER = Sheffield()
