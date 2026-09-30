from api.compat.hacs.exceptions import SourceArgumentException
from api.compat.whitespace import MATCH_CONTAINS, WhitespaceConfig, fetch_collections

TITLE = "Mid Sussex District Council (Whitespace WRP)"
DESCRIPTION = "Source script for Mid Sussex District Council. Fetches collection dates using a four-step web scraping process on the Whitespace Waste & Recycling Portal."
URL = "https://www.midsussex.gov.uk/waste-and-recycling/"

TEST_CASES = {
    "Test Case 1: 23 High Street": {
        "number": "23",
        "street": "HIGH STREET",
        "postcode": "RH17 6TB",
    },
    "Test Case 2: Hapstead Hall": {
        "number": "HAPSTEAD HALL",
        "street": "HIGH STREET",
        "postcode": "RH17 6TB",
    },
    "Test Case 3: The Gardeners Arms": {
        "number": "THE GARDENERS ARMS",
        "street": "SELSFIELD ROAD",
        "postcode": "RH17 6TJ",
    },
}

HOW_TO_GET_ARGUMENTS_DESCRIPTION = {
    "en": "Enter your property's exact Postcode, Street Name, and House Name/Number (or business name) as they appear on the council's website's collection search tool.",
}

PARAM_DESCRIPTIONS = {
    "en": {
        "number": "Enter the house name (e.g., HAPSTEAD HALL) or number (e.g., 11), or the business name.",
        "street": "Enter the street name (e.g., HIGH STREET).",
        "postcode": "Enter the postcode (e.g., RH17 6TB).",
    },
}

PARAM_TRANSLATIONS = {
    "en": {
        "number": "House/Business Name/Number",
        "street": "Street Name",
        "postcode": "Postcode",
    },
}

CONFIG = WhitespaceConfig(
    base_url="https://sms-wrp.whitespacews.com",
    match=MATCH_CONTAINS,
    upper=True,
    icon_map={
        "DOMESTIC FOOD WASTE SERVICE": "mdi:food-apple",
        "DOMESTIC RECYCLING WASTE COLLECTION SERVICE": "mdi:recycle",
        "DOMESTIC REFUSE WASTE COLLECTION SERVICE": "mdi:trash-can",
        "DOMESTIC GARDEN WASTE SERVICE": "mdi:leaf",
    },
    default_icon="mdi:trash-can",
)


class Source:
    def __init__(
        self,
        number: str | None = None,
        street: str = "",
        postcode: str = "",
        house_number: str | None = None,
    ):
        # Support legacy 'house_number' parameter for backwards compatibility
        if number is None and house_number is None:
            raise SourceArgumentException(
                "number", "Either 'number' or 'house_number' must be provided."
            )
        resolved = number or house_number
        assert resolved is not None
        self._number = resolved.strip()
        self._street = street.strip()
        self._postcode = postcode.strip()

    async def fetch(self):
        return await fetch_collections(
            CONFIG,
            number=self._number,
            postcode=self._postcode,
            street=self._street,
        )
