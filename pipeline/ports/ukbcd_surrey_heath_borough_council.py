from api.compat.whitespace import WhitespaceConfig, fetch_collections

TITLE = "Surrey Heath"
URL = "https://asjwsw-wrpsurreyheathmunicipal-live.whitespacews.com/"
TEST_CASES = {
    "Surrey Heath": {"house_number": "36", "postcode": "GU20 6PN"},
}

CONFIG = WhitespaceConfig(
    base_url="https://asjwsw-wrpsurreyheathmunicipal-live.whitespacews.com",
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
