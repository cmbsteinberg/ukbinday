from datetime import date, datetime

from api.compat.curl_cffi_fallback import AsyncClient as _CurlCffiClient
from bs4 import BeautifulSoup
from api.compat.hacs import Collection  # type: ignore[attr-defined]
from api.compat.hacs.exceptions import (
    SourceArgumentNotFound,
    SourceArgumentNotFoundWithSuggestions,
)

TITLE = "Cornwall Council"
DESCRIPTION = "Source for cornwall.gov.uk services for Cornwall Council"
URL = "https://cornwall.gov.uk"
TEST_CASES = {
    "known_uprn": {"uprn": "100040118005"},
    "unknown_uprn": {"postcode": "TR261SP", "house_number": "7"},
    "unknown_uprn_int": {"postcode": "PL17 8PL", "house_number": 3},
    "uprn_with_garden_int_uprn": {"uprn": 100040080721},
}

SEARCH_URLS = {
    "uprn_search": "https://www.cornwall.gov.uk/my-area/",
    "collection_search": "https://www.cornwall.gov.uk/umbraco/Surface/Waste/MyCollectionDays?subscribe=False",
}
ICON_MAP = {
    "Rubbish": "mdi:delete",
    "Recycling": "mdi:recycle",
    "Garden": "mdi:flower",
}


class Source:
    def __init__(
        self, uprn=None, postcode=None, house_number=None
    ):  # argX correspond to the args dict in the source configuration
        self._uprn = uprn
        self._postcode = postcode
        self._house_number = str(house_number) if house_number else None

    async def fetch(self):
        entries = []
        session = _CurlCffiClient(follow_redirects=True)

        # Find the UPRN based on the postcode and the property name/number
        if self._uprn is None:
            args = {"Postcode": self._postcode}
            r = await session.get(SEARCH_URLS["uprn_search"], params=args)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, features="html.parser")
            propertyUprns = soup.find(id="Uprn").find_all("option")
            if len(propertyUprns) == 0:
                raise SourceArgumentNotFound(
                    "postcode",
                    self._postcode,
                )
            for match in propertyUprns:
                if match.text.startswith(self._house_number):
                    self._uprn = match["value"]
            if self._uprn is None:
                raise SourceArgumentNotFoundWithSuggestions(
                    "house_number",
                    self._house_number,
                    [match.text for match in propertyUprns],
                )

        # Get the collection days based on the UPRN (either supplied through arguments or searched for above)
        args = {"uprn": self._uprn}
        r = await session.get(SEARCH_URLS["collection_search"], params=args)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, features="html.parser")
        for collection_div in soup.find_all("div", class_="collection"):
            spans = collection_div.find_all("span")
            if not spans:
                continue
            collection = spans[0].text
            d = spans[-1].text + " " + str(date.today().year)

            entries.append(
                Collection(
                    datetime.strptime(d, "%d %b %Y").date(),
                    collection,
                    icon=ICON_MAP.get(collection),
                )
            )

        return entries
