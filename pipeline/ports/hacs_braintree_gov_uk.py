from bs4 import BeautifulSoup
from curl_cffi.requests import AsyncSession
from dateutil import parser

from api.compat.hacs import Collection, Icons  # type: ignore[attr-defined]
from api.compat.hacs.exceptions import SourceArgumentNotFoundWithSuggestions

TITLE = "Braintree District Council"
DESCRIPTION = "Braintree District Council, UK - Waste Collection"
URL = "https://www.braintree.gov.uk"
TEST_CASES = {
    "30 Boars Tye Road": {"house_number": 30, "postcode": "CM8 3QE"},
    "64 Silver Street": {"house_number": "64", "postcode": "CM8 3QG"},
    "18 St Mary's Road": {"house_number": "1", "postcode": "CM8 3PE"},
    "20 Peel Crescent": {"house_number": "20", "postcode": "CM7 2RS"},
    "Causeway House": {"house_number": "Causeway House", "postcode": "CM7 9HB"},
}
POSTCODE_FIELD = "qe15dda0155d237d1ea161004d1839e3369ed4831_0_0"
ADDRESS_FIELD = "qe15dda0155d237d1ea161004d1839e3369ed4831_1_0"
NAME_MAP = {
    "Non-recyclable waste(grey bin)": "Grey Bin",
    "Outdoorfood caddy": "Food Bin",
    "Outdoor food caddy": "Food Bin",
    "Mixed recycling(blue-lidded bin)": "Mixed Recycling",
    "Paper and card recycling(red-lidded bin)": "Paper & Card",
    "Garden bin(green bin)": "Garden Bin",
}
ICON_MAP = {
    "Grey Bin": Icons.GENERAL_WASTE,
    "Mixed Recycling": Icons.RECYCLING,
    "Paper & Card": Icons.PAPER,
    "Garden Bin": Icons.GARDEN,
    "Food Bin": Icons.BIO_KITCHEN,
}


class Source:
    def __init__(self, postcode: str, house_number: str):
        self.postcode = postcode
        self.house_number = str(house_number)
        self.url = f"{URL}/xfp/form/554"

    @staticmethod
    def _hidden_inputs(soup) -> dict:
        return {
            i["name"]: i.get("value", "")
            for i in soup.find_all("input", {"type": "hidden"})
            if i.get("name") and i["name"] != ADDRESS_FIELD
        }

    async def fetch(self):
        # The form keeps its state in a session cookie (a finished lookup makes the
        # next GET return the results page), so every fetch needs its own cookie jar.
        async with AsyncSession(impersonate="chrome136") as client:
            return await self._fetch(client)

    async def _fetch(self, client):
        # The form carries a per-session __token that must be echoed back
        landing = await client.get(str(self.url))
        landing.raise_for_status()
        form_data = self._hidden_inputs(BeautifulSoup(landing.text, "html.parser"))
        form_data[POSTCODE_FIELD] = self.postcode
        address_lookup = await client.post(str(self.url), data=form_data)
        address_lookup.raise_for_status()
        lookup_soup = BeautifulSoup(address_lookup.text, "html.parser")
        addresses = {}
        for address in lookup_soup.find_all("option"):
            if len(address.get("value", "")) > 5:  # Skip the first option
                addresses[address["value"]] = address.text.strip()
        wanted = self.house_number.strip().lower()
        id = next(
            (
                address
                for address in addresses
                if addresses[address].lower().startswith(wanted + " ")
                or addresses[address].lower().startswith(wanted + ",")
            ),
            None,
        )
        if id is None:
            raise SourceArgumentNotFoundWithSuggestions(
                "house_number", self.house_number, list(addresses.values())
            )
        form_data = self._hidden_inputs(lookup_soup)
        form_data[POSTCODE_FIELD] = self.postcode
        form_data[ADDRESS_FIELD] = id
        form_data["next"] = "Next"
        collection_lookup = await client.post(str(self.url), data=form_data)
        collection_lookup.raise_for_status()
        entries = []
        for results in BeautifulSoup(collection_lookup.text, "html.parser").find_all(
            "div", class_="date_display"
        ):
            try:
                collection_info = results.text.strip().split("\n")
                collection_type = NAME_MAP.get(
                    collection_info[0].strip(), collection_info[0].strip()
                )

                # Skip if no collection date is found
                if len(collection_info) < 2:
                    continue

                collection_date = collection_info[1].strip()

                entries.append(
                    Collection(
                        date=parser.parse(collection_date, dayfirst=True).date(),
                        t=collection_type,
                        icon=ICON_MAP.get(collection_type),
                    )
                )
            except (StopIteration, TypeError):
                pass
        return entries
