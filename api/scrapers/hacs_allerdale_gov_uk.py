from datetime import datetime

from api.compat.hacs import Collection  # type: ignore[attr-defined]
from api.compat.hacs.service.WhitespaceWRP import WhitespaceClient

TITLE = "Allerdale Borough Council"
DESCRIPTION = "Source for www.allerdale.gov.uk services for Allerdale Borough Council."
URL = "https://www.allerdale.gov.uk"
TEST_CASES = {
    "Keswick": {
        "postcode": "CA12 4HU",
        "house_number": "11",
    },
    "Workington": {
        "postcode": "CA14 3NS",
        "house_number": "177",
    },
    "Wigton": {
        "postcode": "CA7 9RS",
        "house_number": "55",
    },
}
ICON_MAP = {
    "Domestic Waste": "mdi:trash-can",
    "Glass Cans and Plastic Recycling": "mdi:recycle",
    "Garden Waste": "mdi:leaf",
}
API_URL = "https://abc-wrp.whitespacews.com/"


class Source:
    def __init__(
        self,
        house_number=None,
        postcode=None,
    ):
        self._house_number = house_number
        self._postcode = postcode
        self._client = WhitespaceClient(API_URL)

    async def fetch(self):
        schedule = await self._client.fetch_schedule(
            house_number=self._house_number,
            postcode=self._postcode,
        )

        entries = []
        for date_str, type_str in schedule:
            collection_type = type_str.replace(" Collection", "").replace(" Service", "")
            entries.append(
                Collection(
                    date=datetime.strptime(date_str, "%d/%m/%Y").date(),
                    t=type_str,
                    icon=ICON_MAP.get(collection_type),
                )
            )
        return entries
