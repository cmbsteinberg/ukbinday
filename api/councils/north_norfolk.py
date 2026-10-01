"""North Norfolk: launch the bin-day journey, look up the property by UPRN, then parse its collection schedule."""

from __future__ import annotations

import asyncio

from api.councils._base import (
    Address,
    Collection,
    Http,
    Meta,
    Scraper,
    UpstreamError,
    parse_date,
    soup,
)

_LAUNCH_URL = "https://forms.north-norfolk.gov.uk/xforms/Launch/New/BinDaysJourney"
_UPRN_URL = "https://forms.north-norfolk.gov.uk/xforms/AddressSearch/GetAddressForUprn"
_COLLECTION_URL = "https://forms.north-norfolk.gov.uk/xforms/Address/Show/CollectionAddress"
_HEADERS = {"user-agent": "Mozilla/5.0"}


def _verification_token(markup: str | bytes) -> str:
    node = soup(markup).select_one('input[name="__RequestVerificationToken"]')
    token = node.get("value") if node else None
    if not token:
        raise UpstreamError("North Norfolk journey page has no verification token")
    return token


class NorthNorfolk(Scraper):
    meta = Meta(
        title="North Norfolk District Council",
        url="https://www.north-norfolk.gov.uk/tasks/environmental-services/view-bin-collections-days/",
        lads=("E07000147",),
        cases={
            "Test_001": {"uprn": "100090878875"},
            "Test_002": {"uprn": "100090883974"},
            "Test_003": {"uprn": "100090880632"},
        },
    )
    requires = frozenset({"uprn"})
    headers = _HEADERS

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        await asyncio.sleep(1)

        r = await http.get(_LAUNCH_URL)
        token = _verification_token(r.content)

        r = await http.post(
            r.url,
            data={
                "__RequestVerificationToken": token,
                "Confirm": "true",
                "BusinessName": "",
                "IsDirty": "False",
                "Journey": "BinDaysJourney",
            },
        )
        token = _verification_token(r.content)

        r = await http.get(
            _UPRN_URL,
            params={"uprn": address.need("uprn"), "localAddress": "True"},
        )
        address_data = r.json()

        payload = {
            "__RequestVerificationToken": token,
            "SearchPostcode": address_data["postcode"],
            "Address": address_data["uprn"],
            "GisUprn": address_data["uprn"],
            "GisUsrn": address_data["bS7666USRN"],
            "GisTownName": address_data["townName"],
            "GisPostTown": address_data["postTown"],
            "GisPostCode": address_data["postcode"],
            "GisAddress": address_data["locAddress1BS7666"],
            "Address1": "",
            "Address2": "",
            "Address3": "",
            "Address4": "",
            "Postcode": "",
            "LocalSearch": "True",
            "DisableManualEntry": "True",
            "ComponentMode": "False",
            "IsDirty": "True",
        }

        r = await http.post(_COLLECTION_URL, data=payload)

        collections: list[Collection] = []
        for item in soup(r.content).find_all("li"):
            details = item.find_all("strong")
            try:
                collections.append(
                    Collection(
                        date=parse_date(details[2].get_text()),
                        type=str(details[0].get_text()),
                    )
                )
            except IndexError:
                continue
        return collections


SCRAPER = NorthNorfolk()
