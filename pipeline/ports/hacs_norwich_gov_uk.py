from api.compat.whitespace import (
    MATCH_NUMBER_STREET,
    WhitespaceConfig,
    fetch_collections,
)

TITLE = "Norwich City Council"
DESCRIPTION = (
    "Source for Norwich City Council bin collection via Whitespace BNR platform"
)
URL = "https://www.norwich.gov.uk/bins-and-recycling"

TEST_CASES = {
    "GoodExample": {
        "house_number": "33",
        "street": "Carrow Road",
        "postcode": "NR1 1HS",
    },
    "FlatAddress": {
        "house_number": "Flat 1",
        "street": "Unthank Road",
        "postcode": "NR2 2RN",
    },
    "UncompletedRoadName": {
        "house_number": "18",
        "street": "Aylsham",
        "postcode": "NR3 3HG",
    },
    "PostcodeMissingSpace": {
        "house_number": "258",
        "street": "North Park Avenue",
        "postcode": "NR47ED",
    },
}

CONFIG = WhitespaceConfig(
    base_url="https://bnr-wrp.whitespacews.com",
    match=MATCH_NUMBER_STREET,
    type_map={
        "Domestic Waste Collection Service": ("Domestic Waste", "mdi:trash-can"),
        "Food Waste Collection Service": ("Food Waste", "mdi:food-apple"),
        "Recycling Collection Service": ("Recycling", "mdi:recycle"),
        "Garden Waste Collection Service": ("Garden Waste", "mdi:leaf"),
    },
    drop_unmapped=True,
)


class Source:
    def __init__(self, house_number: str, street: str, postcode: str):
        self._house_number = house_number
        self._street = street
        self._postcode = postcode

    async def fetch(self):
        entries = await fetch_collections(
            CONFIG,
            number=self._house_number,
            postcode=self._postcode,
            street=self._street,
        )
        if not entries:
            raise ValueError("No collection data returned for the selected address")
        return entries
