from api.compat.hacs.itouchvision import fetch_collections

TITLE = "Hyndburn Borough Council"
URL = "https://www.hyndburnbc.gov.uk/"
TEST_CASES = {
    "test": {"uprn": "100010439798"},
}


class Source:
    def __init__(self, uprn: str | int):
        self._uprn = uprn

    async def fetch(self):
        return await fetch_collections(
            uprn=self._uprn,
            client_id=157,
            council_id=34508,
            api_url="https://itouchvision.app/portal/itouchvision/kmbd/collectionDay",
        )
