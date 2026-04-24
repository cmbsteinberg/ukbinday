from api.compat.hacs.itouchvision import fetch_collections

TITLE = "Blaenau Gwent County Borough Council"
URL = "https://www.blaenau-gwent.gov.uk/"
TEST_CASES = {
    "test": {"uprn": "100100457787"},
}


class Source:
    def __init__(self, uprn: str | int):
        self._uprn = uprn

    async def fetch(self):
        return await fetch_collections(
            uprn=self._uprn,
            client_id=106,
            council_id=35,
            api_url="https://iweb.itouchvision.com/portal/itouchvision/kmbd/collectionDay",
        )
