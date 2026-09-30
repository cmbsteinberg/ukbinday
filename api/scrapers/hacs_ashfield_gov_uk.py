import datetime

from api.compat.curl_cffi_fallback import AsyncClient as _CurlCffiClient
from api.compat.hacs import Collection, Icons
from api.compat.hacs.exceptions import (
    SourceArgumentNotFound,
    SourceArgumentNotFoundWithSuggestions,
)

TITLE = "Ashfield District Council"
DESCRIPTION = "Source for ashfield.gov.uk, Ashfield District Council, UK"
URL = "https://www.ashfield.gov.uk"
TEST_CASES = {
    "11 Maun View Gardens, Sutton-in-Ashfield": {"uprn": 10001336299},
    "101 Main Street, Huthwaite": {"postcode": "NG17 2LQ", "uprn": "100031253415"},
    "1 Acacia Avenue, Kirkby-in-Ashfield": {"postcode": "NG17 9BH", "house_number": "1"},
    "Council Offices, Kirkby-in-Ashfield": {
        "postcode": "NG178ZA",
        "name": "COUNCIL OFFICES",
    },
}

API_URLS = {
    "address_search": "https://www.ashfield.gov.uk/api/address/search/{postcode}",
    "collection": "https://www.ashfield.gov.uk/api/address/collections/{uprn}",
}

ICON_MAP = {
    "Residual Waste Collection Service": Icons.GENERAL_WASTE,
    "Domestic Recycling Collection Service": Icons.GENERAL_WASTE,
    "Domestic Glass Collection Service": Icons.GLASS,
    "Garden Waste Collection Service": Icons.GARDEN,
}

NAMES = {
    "Residual Waste Collection Service": "Red (rubbish)",
    "Domestic Recycling Collection Service": "Green (recycling)",
    "Domestic Glass Collection Service": "Blue (glass)",
    "Garden Waste Collection Service": "Brown (garden)",
}


class Source:
    def __init__(self, postcode=None, house_number=None, name=None, uprn=None):
        self._postcode = postcode
        self._house_number = house_number
        self._name = name
        self._uprn = uprn

    async def fetch(self):
        if not self._uprn:
            if not self._postcode:
                raise ValueError("postcode is required when uprn is not provided")
            if not (self._name or self._house_number):
                raise ValueError(
                    "Either name or house_number must be provided when uprn is not provided"
                )
            # look up the UPRN for the address
            q = str(API_URLS["address_search"]).format(postcode=self._postcode)
            r = await _CurlCffiClient(follow_redirects=True).get(q, timeout=30)
            r.raise_for_status()
            addresses = r.json()["results"]

            if not addresses:
                raise SourceArgumentNotFound("postcode", self._postcode)

            matching = []
            if self._name:
                name_cf = self._name.casefold()
                for x in addresses:
                    dpa = x.get("DPA") or {}
                    building_name = dpa.get("BUILDING_NAME")
                    if building_name and building_name.casefold() == name_cf:
                        matching.append(x)
            elif self._house_number:
                for x in addresses:
                    dpa = x.get("DPA") or {}
                    if dpa.get("BUILDING_NUMBER") == self._house_number:
                        matching.append(x)

            if matching:
                first_dpa = matching[0].get("DPA") or {}
                uprn_value = first_dpa.get("UPRN")
                if uprn_value:
                    self._uprn = int(uprn_value)

            if not self._uprn:
                raise SourceArgumentNotFoundWithSuggestions(
                    argument=(
                        "name"
                        if self._name
                        else "house_number"
                        if self._house_number
                        else "postcode"
                    ),
                    value=self._name or self._house_number or self._postcode,
                    suggestions=[
                        f"{(x.get('DPA') or {}).get('BUILDING_NUMBER', '')} {(x.get('DPA') or {}).get('BUILDING_NAME', '')}".strip()
                        for x in addresses
                    ],
                )
        else:
            # Ensure UPRN is an integer
            self._uprn = int(self._uprn)

        q = str(API_URLS["collection"]).format(uprn=self._uprn)

        r = await _CurlCffiClient(follow_redirects=True).get(q, timeout=30)
        r.raise_for_status()

        collections = r.json()["collections"]
        entries = []

        if collections:
            for collection in collections:
                entries.append(
                    Collection(
                        date=datetime.datetime.strptime(
                            collection["date"], "%d/%m/%Y %H:%M:%S"
                        ).date(),
                        t=NAMES.get(collection["service"], collection["service"]),
                        icon=ICON_MAP.get(collection["service"]),
                    )
                )

        return entries
