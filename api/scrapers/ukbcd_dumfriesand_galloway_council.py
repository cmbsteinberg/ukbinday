from datetime import datetime, timedelta

import httpx
from bs4 import BeautifulSoup
from icalevents.icalevents import events

from api.compat.ukbcd.common import *
from api.compat.ukbcd.get_bin_data import AbstractGetBinDataClass
from api.compat import httpx_helpers as _http

SEARCH_URL = "https://www.dumfriesandgalloway.gov.uk/bins-recycling/waste-collection-schedule/find"
ICS_BASE = "https://www.dumfriesandgalloway.gov.uk/bins-recycling/waste-collection-schedule/download"


async def _resolve_uprn(postcode, uprn=None, paon=None):
    """Resolve UPRN via postcode address search if not provided."""
    if uprn:
        return str(uprn)

    if not postcode:
        raise ValueError("Provide a postcode or UPRN.")

    resp = await _http.get(SEARCH_URL, params={"postcode": postcode}, timeout=30)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")
    select_el = soup.find("select", {"name": "uprn"})
    if not select_el:
        raise ValueError(f"No addresses found for postcode: {postcode}")

    options = [(opt["value"], opt.text.strip()) for opt in select_el.find_all("option") if opt.get("value")]
    if not options:
        raise ValueError(f"No addresses found for postcode: {postcode}")

    if paon:
        paon_norm = str(paon).strip().upper()
        for val, text in options:
            text_upper = text.upper()
            if text_upper.startswith(paon_norm + " ") or text_upper.startswith(paon_norm + ","):
                return val
        for val, text in options:
            if paon_norm in text.upper():
                return val

    if paon:
        raise ValueError(
            f"Address not found for PAON={paon} in postcode {postcode}"
        )
    return options[0][0]


class CouncilClass(AbstractGetBinDataClass):
    async def parse_data(self, page: str, **kwargs) -> dict:
        data = {"bins": []}

        user_uprn = kwargs.get("uprn")
        user_postcode = kwargs.get("postcode")
        user_paon = kwargs.get("paon")

        resolved_uprn = await _resolve_uprn(user_postcode, uprn=user_uprn, paon=user_paon)

        ics_url = f"{ICS_BASE}/{resolved_uprn}"

        ics_resp = await _http.get(ics_url, timeout=30)
        ics_resp.raise_for_status()
        ics_text = ics_resp.text
        if "<br" in ics_text or "<html" in ics_text.lower() or "VCALENDAR" not in ics_text:
            raise ValueError(
                f"ICS feed returned invalid data for UPRN {resolved_uprn} (status {ics_resp.status_code}, url {ics_url})"
            )

        now = datetime.now()
        future = now + timedelta(days=60)

        upcoming_events = events(string_content=ics_text, start=now, end=future)

        for event in sorted(upcoming_events, key=lambda e: e.start):
            if event.summary and event.start:
                collections = event.summary.split(",")
                for collection in collections:
                    data["bins"].append(
                        {
                            "type": collection.strip(),
                            "collectionDate": event.start.date().strftime(
                                date_format
                            ),
                        }
                    )

        return data


# --- Adapter for Project API ---
from api.compat.hacs import Collection  # type: ignore[attr-defined]

TITLE = "Dumfries and Galloway Council"
URL = "https://www.dumfriesandgalloway.gov.uk"
TEST_CASES = {}


class Source:
    def __init__(self, uprn: str | None = None, postcode: str | None = None, house_number: str | None = None):
        self.uprn = uprn
        self.postcode = postcode
        self.house_number = house_number
        self._scraper = CouncilClass()

    async def fetch(self) -> list[Collection]:
        from datetime import datetime

        kwargs = {}
        if self.uprn: kwargs['uprn'] = self.uprn
        if self.postcode: kwargs['postcode'] = self.postcode
        if self.house_number: kwargs['paon'] = self.house_number

        data = await self._scraper.parse_data("", **kwargs)

        entries = []
        if isinstance(data, dict) and "bins" in data:
            for item in data["bins"]:
                bin_type = item.get("type")
                date_str = item.get("collectionDate")
                if not bin_type or not date_str:
                    continue
                try:
                    if "-" in date_str:
                        dt = datetime.strptime(date_str, "%Y-%m-%d").date()
                    elif "/" in date_str:
                        dt = datetime.strptime(date_str, "%d/%m/%Y").date()
                    else:
                        continue
                    entries.append(Collection(date=dt, t=bin_type, icon=None))
                except ValueError:
                    continue
        return entries
