import re

import httpx
from bs4 import BeautifulSoup

from api.compat.ukbcd.common import *
from api.compat.ukbcd.get_bin_data import AbstractGetBinDataClass
from api.compat import httpx_helpers as _http

BASE_URL = "https://www.westmorlandandfurness.gov.uk/bins-recycling-and-street-cleaning/waste-collection-schedule"


async def _resolve_uprn(postcode, uprn=None, paon=None):
    """Resolve UPRN via postcode address search if not provided."""
    if uprn:
        return str(uprn)

    if not postcode:
        raise ValueError("Provide a postcode or UPRN.")

    resp = await _http.get(
        f"{BASE_URL}/find",
        params={"postcode": postcode},
        timeout=30,
    )
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
            if re.search(rf"\b{re.escape(paon_norm)}\b", text.upper()):
                return val

    return options[0][0]


class CouncilClass(AbstractGetBinDataClass):
    async def parse_data(self, page: str, **kwargs) -> dict:
        user_uprn = kwargs.get("uprn")
        user_postcode = kwargs.get("postcode")
        user_paon = kwargs.get("paon") or kwargs.get("house_number")

        resolved_uprn = await _resolve_uprn(user_postcode, uprn=user_uprn, paon=user_paon)

        bindata = {"bins": []}

        URI = f"{BASE_URL}/view/{resolved_uprn}"

        current_year = datetime.now().year
        current_month = datetime.now().month

        response = await _http.get(URI, timeout=30)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")
        schedule = soup.findAll("div", {"class": "waste-collection__month"})
        for month in schedule:
            collectionmonth = datetime.strptime(month.find("h3").text, "%B")
            collectionmonth = collectionmonth.month
            collectiondays = month.findAll("li", {"class": "waste-collection__day"})
            for collectionday in collectiondays:
                day = collectionday.find(
                    "span", {"class": "waste-collection__day--day"}
                ).text.strip()
                collectiondate = datetime.strptime(day, "%d")
                collectiondate = collectiondate.replace(month=collectionmonth)
                bintype = collectionday.find(
                    "span", {"class": "waste-collection__day--type"}
                ).text.strip()

                # The calendar shows the next 12 months, so if the month steps back in
                # time, assume it is for the following year.
                if (collectiondate.month < current_month):
                    collectiondate = collectiondate.replace(year=(current_year + 1))
                else:
                    collectiondate = collectiondate.replace(year=current_year)

                dict_data = {
                    "type": bintype,
                    "collectionDate": collectiondate.strftime("%d/%m/%Y"),
                }
                bindata["bins"].append(dict_data)

        bindata["bins"].sort(
            key=lambda x: datetime.strptime(x.get("collectionDate"), "%d/%m/%Y")
        )

        return bindata


# --- Adapter for Project API ---
from api.compat.hacs import Collection  # type: ignore[attr-defined]

TITLE = "Westmorland and Furness"
URL = "https://www.westmorlandandfurness.gov.uk/"
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
