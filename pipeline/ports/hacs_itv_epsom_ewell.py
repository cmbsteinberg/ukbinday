from api.compat.hacs.itouchvision import fetch_collections

TITLE = "Epsom and Ewell Borough Council"
URL = "https://www.epsom-ewell.gov.uk/"
TEST_CASES = {
    "test": {"uprn": "100061349867"},
}


class Source:
    def __init__(self, uprn: str | int):
        self._uprn = uprn

    async def fetch(self):
        return await fetch_collections(
            uprn=self._uprn,
            client_id=138,
            council_id=140,
            api_url="https://iweb.itouchvision.com/portal/itouchvision/kmbd/collectionDay",
        )
