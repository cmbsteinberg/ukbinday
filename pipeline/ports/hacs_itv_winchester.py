from api.compat.hacs.itouchvision import fetch_collections

TITLE = "Winchester City Council"
URL = "https://www.winchester.gov.uk"
TEST_CASES = {
    "test": {"uprn": "10090844134"},
}


class Source:
    def __init__(self, uprn: str | int):
        self._uprn = uprn

    async def fetch(self):
        return await fetch_collections(
            uprn=self._uprn,
            client_id=43,
            council_id=433,
            api_url="https://iweb.itouchvision.com/portal/itouchvision/kmbd/collectionDay",
        )
