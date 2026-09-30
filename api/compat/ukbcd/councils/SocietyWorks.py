from datetime import timedelta
import re
from abc import abstractmethod
import httpx
from bs4 import BeautifulSoup
from icalevents.icalparser import parse_events

from api.compat.ukbcd.common import date_format
from api.compat.ukbcd.get_bin_data import AbstractGetBinDataClass


class SocietyWorksClass(AbstractGetBinDataClass):
    """
    Shared implementation for services using the same backend software by SocietyWorks
    """

    @property
    @abstractmethod
    def BASE_URL(self):
        pass

    def __init__(self, *args, **kwargs):
        """Set up a shared requests session"""
        super().__init__(*args, **kwargs)
        self.session = httpx.AsyncClient(follow_redirects=True)
        headers = {
            "User-Agent": "uk-bin-collection/1.0 (+https://github.com/robbrad/UKBinCollectionData)",
        }
        self.session.headers.update(headers)

    async def _get(self, url):
        resp = await self.session.get(
            f"{self.BASE_URL}{url}", follow_redirects=False, timeout=30
        )
        return resp

    async def _uprn_to_property_id(self, uprn):
        """Takes a UPRN (might be a property ID) and tries to look up a property ID"""
        resp = await self._get(f"property/{uprn}")
        if resp.status_code == 404:
            # If no lookup, assume we might have been given a property ID directly
            return uprn
        resp.raise_for_status()
        location = resp.headers.get("Location")
        if not location:
            raise ValueError(
                f"Expected a redirect with a Location header resolving UPRN {uprn}, "
                f"got status {resp.status_code} with none."
            )
        property_id = location.split("/")[-1]
        return property_id

    async def _address_to_property_id(self, postcode, addr):
        """Takes a postcode and address line and looks up its property ID"""
        resp = await self.session.post(
            f"{self.BASE_URL}waste", data={"postcode": postcode}, timeout=30
        )
        resp.raise_for_status()
        soup = BeautifulSoup(resp.content, "html.parser")
        select = soup.find("select", {"id": "address"})
        if not select:
            return None
        addr_lower = (addr or "").strip().lower()
        # Match the house name/number at the start of the option text (e.g.
        # "54 Greyhound Road, Sutton, SM1 4BJ") rather than as a substring
        # anywhere in it - a bare `in` check would let addr "6" wrongly
        # match "56 Greyhound Road" before ever reaching a real "6 ...".
        for address in select.find_all("option"):
            text = address.get_text(strip=True).lower()
            if text.startswith(addr_lower + " ") or text == addr_lower:
                return address.get("value")
        return None

    async def parse_data(self, page: str, **kwargs) -> dict:
        """Takes provided user data and fetches bin day iCal information"""
        user_uprn = kwargs.get("uprn")
        user_postcode = kwargs.get("postcode")
        user_paon = kwargs.get("paon")
        user_url = kwargs.get("url")

        property_id = None
        # Keep handling Bromley/Kingston old way, with ID in passed URL.
        # user_url is None in this API (the adapter passes postcode/paon, not
        # a page URL), so guard the match instead of assuming it is a string.
        if user_url and (m := re.search("waste/([0-9]+)", user_url)):
            property_id = m.group(1)
        elif user_uprn:
            if not user_uprn.isdigit():
                raise ValueError("Invalid UPRN/ID")
            property_id = await self._uprn_to_property_id(user_uprn)
        elif user_postcode and user_paon:
            property_id = await self._address_to_property_id(user_postcode, user_paon)

        if not property_id:
            raise ValueError(
                "Could not resolve property. Provide postcode+address or valid UPRN."
            )

        resp = await self._get(f"waste/{property_id}/calendar.ics")
        resp.raise_for_status()
        text = resp.text
        if "VCALENDAR" not in text:
            raise ValueError(
                f"ICS feed returned invalid data for ID {property_id} (status {resp.status_code})"
            )

        data = {"bins": []}
        collections = parse_events(text, default_span=timedelta(days=60), sort=True)
        for event in collections:
            if event.summary and event.start:
                data["bins"].append(
                    {
                        "type": event.summary,
                        "collectionDate": event.start.date().strftime(date_format),
                    }
                )

        return data
