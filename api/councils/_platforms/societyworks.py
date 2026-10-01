"""SocietyWorks "waste" sites (Brent, Merton, Sutton, Bromley...), `<host>/waste`.

Every site runs the same flow:

1. Find the property id: `GET property/<uprn>` answers with a redirect whose
   `Location` ends in the id (a 404 means the number was already an id), or
   `POST waste` with the postcode and pick the property from `select#address`.
2. `GET waste/<id>/calendar.ics` and read the events.

What differs per council is the host, in `SocietyWorksConfig`.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from api.councils._base import (
    Address,
    Collection,
    Http,
    InputError,
    Platform,
    UpstreamError,
    match_address,
    parse_ics,
    soup,
    text_of,
)

_TIMEOUT = 30


@dataclass(frozen=True, slots=True, kw_only=True)
class SocietyWorksConfig:
    base_url: str
    """With a trailing slash: "https://recyclingservices.brent.gov.uk/"."""


class SocietyWorks(Platform[SocietyWorksConfig]):
    requires = frozenset()  # a UPRN, or a postcode plus the house number
    headers: Mapping[str, str] = MappingProxyType(
        {"User-Agent": "uk-bin-collection/1.0 (+https://github.com/robbrad/UKBinCollectionData)"}
    )

    async def _uprn_to_property_id(self, http: Http, uprn: str) -> str:
        r = await http.get(f"{self.config.base_url}property/{uprn}", follow_redirects=False, timeout=_TIMEOUT, check=False)
        if r.status_code == 404:
            return uprn  # not a UPRN: assume we were given a property id
        if not r.is_redirect:
            r.raise_for_status()
        location = r.headers.get("Location")
        if not location:
            raise UpstreamError(f"Expected a redirect resolving UPRN {uprn}, got status {r.status_code} without one")
        return location.split("/")[-1]

    async def _address_to_property_id(self, http: Http, address: Address) -> str:
        r = await http.post(
            f"{self.config.base_url}waste", data={"postcode": address.need("postcode")}, timeout=_TIMEOUT
        )
        options = soup(r.content).select("select#address option")
        chosen = match_address(address, options, text=lambda o: text_of(o))
        value = chosen.get("value")
        if not value:
            raise InputError("The council's address list has no property id for this address")
        return str(value)

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        if address.uprn:
            property_id = await self._uprn_to_property_id(http, address.uprn)
        elif address.postcode and address.house_number:
            property_id = await self._address_to_property_id(http, address)
        else:
            raise InputError("Provide a UPRN, or a postcode and house number")

        r = await http.get(
            f"{self.config.base_url}waste/{property_id}/calendar.ics", follow_redirects=False, timeout=_TIMEOUT
        )
        if "VCALENDAR" not in r.text:
            raise UpstreamError(f"ICS feed returned invalid data for ID {property_id} (status {r.status_code})")
        return [Collection(event.date, event.summary) for event in parse_ics(r.text)]
