from datetime import datetime

from bs4 import BeautifulSoup

from api.compat.curl_cffi_fallback import AsyncClient as _CurlCffiClient
from api.compat.hacs import Collection  # type: ignore[attr-defined]
from api.compat.hacs.exceptions import SourceArgumentNotFound

TITLE = "Conwy County Borough Council"
DESCRIPTION = "Source for Conwy County Borough Council."
URL = "https://www.conwy.gov.uk/"
TEST_CASES = {
    "50000009637": {"uprn": 50000009637},
    "100101037037": {"uprn": "100101037037"},
    "50000007574": {"uprn": 50000007574},
}


ICON_MAP = {
    "garden": "mdi:leaf",
    "electrical": "mdi:battery",
    "refuse": "mdi:trash-can",
    "recycle": "mdi:recycle",
}


API_URL = (
    "https://www.conwy.gov.uk/Contensis-Forms/erf/collection-result-soap-xmas2025.asp"
)


class Source:
    def __init__(self, uprn: str | int):
        self._uprn: str | int = uprn

    async def fetch(self):
        r = await _CurlCffiClient(follow_redirects=True).get(API_URL, params={"uprn": self._uprn, "ilangid": 1})
        r.raise_for_status()

        entries = []

        soup = BeautifulSoup(r.text, "html.parser")
        collection_dates = soup.select(".containererf")

        if not collection_dates:
            raise SourceArgumentNotFound("uprn", self._uprn)

        for collection in collection_dates:
            date_str = collection.select_one("#main #content").text.strip()
            bin_types = [el.text for el in collection.select("#main1 li")]

            date = datetime.strptime(date_str, "%A, %d/%m/%Y").date()

            for bin_type in bin_types:
                icon = ICON_MAP.get(bin_type.split(" ")[0].lower())  # Collection icon
                entries.append(Collection(date=date, t=bin_type, icon=icon))

        return entries
