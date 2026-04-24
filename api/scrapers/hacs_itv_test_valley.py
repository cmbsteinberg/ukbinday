from api.compat.hacs.itouchvision import fetch_collections

TITLE = "Test Valley Borough Council"
URL = "https://www.testvalley.gov.uk/"
TEST_CASES = {
    "test": {"uprn": "100060571645"},
}


class Source:
    def __init__(self, uprn: str | int):
        self._uprn = uprn

    async def fetch(self):
        return await fetch_collections(
            uprn=self._uprn,
            client_id=94,
            council_id=390,
            api_url="https://iweb.itouchvision.com/portal/itouchvision/kmbd/collectionDay",
        )
