from api.compat.whitespace import MATCH_PREFIX, WhitespaceConfig, fetch_collections

TITLE = "Waverley Borough Council"
DESCRIPTION = "Source for www.waverley.gov.uk services for Waverley Borough Council."
URL = "https://waverley.gov.uk"
TEST_CASES = {
    "Example": {
        "postcode": "GU8 5QQ",
        "house_number": "1",
        "street": "Gasden Drive",
    },
    "Example No Postcode Space": {
        "postcode": "GU85QQ",
        "house_number": "1",
        "street": "Gasden Drive",
    },
}

CONFIG = WhitespaceConfig(
    base_url="https://wav-wrp.whitespacews.com",
    match=MATCH_PREFIX,
    strip_suffixes=(" Collection Service",),
    icon_map={
        "Domestic Waste": "mdi:trash-can",
        "Recycling": "mdi:recycle",
        "Garden Waste": "mdi:leaf",
        "Food Waste": "mdi:food-apple",
    },
)


class Source:
    def __init__(
        self,
        house_number=None,
        street=None,
        town=None,
        postcode=None,
    ):
        self._house_number = house_number
        self._street = street
        self._town = town
        self._postcode = postcode

    async def fetch(self):
        return await fetch_collections(
            CONFIG,
            number=self._house_number,
            postcode=self._postcode or "",
            street=self._street or "",
            town=self._town or "",
        )
