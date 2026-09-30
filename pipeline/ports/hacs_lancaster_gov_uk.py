from typing import Union

from api.compat.whitespace import WhitespaceConfig, fetch_collections

TITLE = "Lancaster City Council"
DESCRIPTION = "Source for lancaster.gov.uk services for Lancaster City Council, UK."
URL = "https://lancaster.gov.uk"
TEST_CASES = {
    "1 Queen Street Lancaster, LA1 1RS": {"house_number": 1, "postcode": "LA1 1RS"}
}

CONFIG = WhitespaceConfig(
    base_url="https://lcc-wrp.whitespacews.com",
    strip_suffixes=(
        " Collection Service",
        " Collection - refer to calendar for stream",
    ),
    icon_map={
        "Domestic Waste": "mdi:trash-can",
        "Garden Waste": "mdi:leaf",
        "Recycling": "mdi:recycle",
        "Food Waste": "mdi:food",
    },
    default_icon="mdi:trash-can",
)


class Source:
    def __init__(
        self, postcode: str, house_number: Union[int, str, None] = None
    ) -> None:
        self._house_number = house_number
        self._postcode = postcode

    async def fetch(self):
        return await fetch_collections(
            CONFIG, number=self._house_number, postcode=self._postcode
        )
