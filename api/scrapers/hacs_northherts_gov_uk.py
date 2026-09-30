from api.compat.hacs import Collection, Icons
from api.compat.hacs.service.uk_cloud9_apps import Cloud9Client

TITLE = "North Herts Council"
DESCRIPTION = "Source for www.north-herts.gov.uk services for North Herts Council."
URL = "https://www.north-herts.gov.uk/"
TEST_CASES = {
    "Example": {
        "postcode": "SG4 9QY",
        "house_number": "26",
        "street": "BENSLOW RISE",
    },
    "Example No Postcode Space": {
        "postcode": "SG49QY",
        "house_number": "26",
        "street": "BENSLOW RISE",
    },
    "Example fuzzy matching": {
        "postcode": "SG6 4EG",
        "house_number": "4",
        "street": "Wilbury Road",
    },
    "Example garden waste": {
        "postcode": "SG8 5BN",
        "house_number": "37",
        "street": "Heathfield",
    },
}
ICON_MAP = {
    "refuse": Icons.GENERAL_WASTE,
    "residual": Icons.GENERAL_WASTE,
    "recycle": Icons.RECYCLING,
    "recycling": Icons.RECYCLING,
    "garden": Icons.GARDEN,
    "food": Icons.BIO_KITCHEN,
    "paper": Icons.PAPER,
    "card": Icons.PAPER,
}


class Source:
    def __init__(
        self,
        house_number: str | None = None,
        street: str | None = None,
        town: str | None = None,
        postcode: str | None = None,
    ):
        self._client = Cloud9Client("northherts", icon_keywords=ICON_MAP)
        self._house_number = house_number
        self._street = street
        self._town = town
        self._postcode = postcode

    async def fetch(self) -> list[Collection]:
        search_query = " ".join(
            part.strip()
            for part in (
                self._house_number,
                self._street,
                self._town,
                self._postcode,
            )
            if isinstance(part, str) and part.strip()
        )
        return self._client.fetch_by_address(
            postcode=self._postcode,
            address_string=search_query,
            address_name_number=self._house_number,
            street=self._street,
            town=self._town,
            argument_name="postcode",
        )
