from api.compat.whitespace import WhitespaceConfig, fetch_collections

TITLE = "Lancaster"
URL = "https://lcc-wrp.whitespacews.com"
TEST_CASES = {
    "Lancaster": {"house_number": "1", "postcode": "LA1 1RS"},
}

CONFIG = WhitespaceConfig(
    base_url="https://lcc-wrp.whitespacews.com",
    strip_suffixes=(
        " Collection Service",
        " Collection - refer to calendar for stream",
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
