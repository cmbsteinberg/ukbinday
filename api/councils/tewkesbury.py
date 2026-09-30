"""Tewkesbury: looks up the next collection by UPRN, with a deprecated postcode fallback."""

from __future__ import annotations

from datetime import datetime
from urllib.parse import quote

from api.councils._base import (
    Address,
    Collection,
    Http,
    InputError,
    Meta,
    Scraper,
    UpstreamError,
)

_DEPRECATED_API_URL = "https://api-2.tewkesbury.gov.uk/general/rounds/%s/nextCollection"
_API_URL = "https://api-2.tewkesbury.gov.uk/incab/rounds/%s/next-collection"


class Tewkesbury(Scraper):
    meta = Meta(
        title="Tewkesbury Borough Council",
        url="https://www.tewkesbury.gov.uk",
        lads=("E07000083",),
        cases={
            "UPRN example": {"uprn": "100120544973"},
            "Deprecated postcode": {"postcode": "GL20 5TT"},
            "Deprecated postcode No Spaces": {"postcode": "GL205TT"},
        },
    )
    requires = frozenset()

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        if address.uprn is not None:
            identifier = address.uprn
            api_url = _API_URL
        else:
            if address.postcode is None:
                raise InputError("Tewkesbury needs a UPRN or postcode")
            identifier = address.postcode
            api_url = _DEPRECATED_API_URL

        request_url = api_url % quote(identifier)
        response = await http.get(request_url)
        data = response.json()

        waste_type_map = {
            "refuse": "Refuse",
            "recycling": "Recycling",
            "food": "Food",
            "garden": "Garden",
        }
        collections = []
        for waste_key, waste_label in waste_type_map.items():
            if waste_key not in data:
                continue
            date_str = data[waste_key].get("nextCollectionDate")
            if not date_str:
                continue
            collections.append(
                Collection(
                    date=datetime.fromisoformat(date_str.replace("Z", "+00:00")).date(),
                    type=waste_label,
                )
            )

        if not collections:
            raise UpstreamError(f"No collection data returned for identifier: {identifier!r}")
        return collections


SCRAPER = Tewkesbury()
