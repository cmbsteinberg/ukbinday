from api.compat.whitespace import WhitespaceConfig, fetch_collections

TITLE = "Norwich"
URL = "https://bnr-wrp.whitespacews.com"
TEST_CASES = {
    "Norwich": {"house_number": "2", "postcode": "NR2 3TT"},
}

CONFIG = WhitespaceConfig(base_url="https://bnr-wrp.whitespacews.com")


class Source:
    def __init__(self, postcode: str | None = None, house_number: str | None = None):
        self.postcode = postcode
        self.house_number = house_number

    async def fetch(self):
        return await fetch_collections(
            CONFIG, number=self.house_number, postcode=self.postcode or ""
        )
