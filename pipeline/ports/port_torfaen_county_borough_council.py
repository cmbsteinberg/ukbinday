"""Torfaen County Borough Council -- iTouchVision (iCollectionDay) backend.

The council's "bins-recycling-streets" page links to
iportal.itouchvision.com/icollectionday (a React app). The app first calls
``gdsv5/util/igetclientdetails`` with the council's uuid to learn its
``P_CLIENT_ID`` (80) and ``P_COUNCIL_ID`` (397), then GETs
``kmbd/collectionDay`` with an AES-CBC encrypted ``P_PARAMETER`` header
(shared key/IV from the JS bundle) and decrypts the hex response.

Flow: encrypted GET with UPRN -> decrypted JSON of per-service dates.
"""

from api.compat.hacs.itouchvision import fetch_collections

TITLE = "Torfaen County Borough Council"
DESCRIPTION = "Source for bin collections from Torfaen County Borough Council."
URL = "https://www.torfaen.gov.uk/"
TEST_CASES = {
    "NP4 6LU": {"uprn": "100100800320"},
    "NP44 3DN": {"uprn": "100100789478"},
    "NP4 8HQ": {"uprn": "100100798047"},
}


class Source:
    def __init__(self, uprn: str | int):
        self._uprn = uprn

    async def fetch(self):
        return await fetch_collections(
            uprn=self._uprn,
            client_id=80,
            council_id=397,
            api_url="https://iweb.itouchvision.com/portal/itouchvision/kmbd/collectionDay",
        )
