from api.compat.whitespace import WhitespaceConfig, fetch_collections

TITLE = "Woking"
URL = "https://asjwsw-wrpwokingmunicipal-live.whitespacews.com/"
TEST_CASES = {
    "Woking": {"house_number": "2", "postcode": "GU21 4JY"},
}

CONFIG = WhitespaceConfig(
    base_url="https://asjwsw-wrpwokingmunicipal-live.whitespacews.com",
    type_replace=(
        (
            "Batteries-small electricals-textiles",
            "Batteries/small electricals/textiles",
        ),
    ),
)


class Source:
    def __init__(self, postcode: str | None = None, house_number: str | None = None):
        self.postcode = postcode
        self.house_number = house_number

    async def fetch(self):
        return await fetch_collections(
            CONFIG, number=self.house_number, postcode=self.postcode or ""
        )
