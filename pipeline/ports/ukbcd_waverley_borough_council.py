from api.compat.whitespace import MATCH_PREFIX, WhitespaceConfig, fetch_collections

TITLE = "Waverley"
URL = "https://wav-wrp.whitespacews.com/"
TEST_CASES = {
    "Waverley": {"house_number": "23", "postcode": "GU9 9QG"},
}

CONFIG = WhitespaceConfig(
    base_url="https://wav-wrp.whitespacews.com",
    match=MATCH_PREFIX,
)


class Source:
    def __init__(self, postcode: str | None = None, house_number: str | None = None):
        self.postcode = postcode
        self.house_number = house_number

    async def fetch(self):
        return await fetch_collections(
            CONFIG, number=self.house_number, postcode=self.postcode or ""
        )
