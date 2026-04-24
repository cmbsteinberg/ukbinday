from api.compat.hacs.itouchvision import fetch_collections

TITLE = "Somerset Council"
URL = "https://www.somerset.gov.uk/"
TEST_CASES = {
    "test": {"uprn": "30071272"},
}


class Source:
    def __init__(self, uprn: str | int):
        self._uprn = uprn

    async def fetch(self):
        return await fetch_collections(
            uprn=self._uprn,
            client_id=129,
            council_id=34493,
            api_url="https://iweb.itouchvision.com/portal/itouchvision/kmbd/collectionDay",
        )
