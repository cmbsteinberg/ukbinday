"""Reigate & Banstead: an AchieveForms lookup returns XML containing the collection schedule HTML."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from time import time_ns

from api.councils._base import Address, Collection, Http, Meta, Scraper, soup

_HEADERS = {"user-agent": "Mozilla/5.0"}
_AUTH_URL = (
    "https://my.reigate-banstead.gov.uk/authapi/isauthenticated"
    "?uri=https%3A%2F%2Fmy.reigate-banstead.gov.uk%2Fservice%2FBins_and_recycling___collections_calendar"
    "&hostname=my.reigate-banstead.gov.uk&withCredentials=true"
)
_BASE = "https://my.reigate-banstead.gov.uk/apibroker/runLookup"


class ReigateAndBanstead(Scraper):
    meta = Meta(
        title="Reigate & Banstead Borough Council",
        url="https://reigate-banstead.gov.uk",
        lads=("E07000211",),
        cases={
            "Test_001": {"uprn": "68110755"},
            "Test_003": {"uprn": "68101147"},
        },
    )
    requires = frozenset({"uprn"})
    headers = _HEADERS

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        sid_request = await http.get(_AUTH_URL)
        sid = sid_request.json()["auth-session"]

        timestamp = time_ns() // 1_000_000
        token_request = await http.get(
            f"{_BASE}?id=595ce0f243541&repeat_against=&noRetry=true&getOnlyTokens=undefined"
            f"&log_id=&app_name=AF-Renderer::Self&_={timestamp}&sid={sid}"
        )
        token_data = token_request.json()
        token_string = ET.fromstring(token_data["data"])[0][0][1][0][0].text

        timestamp = time_ns() // 1_000_000
        min_date = datetime.today().strftime("%Y-%m-%d")
        max_date = (datetime.today() + timedelta(days=28)).strftime("%Y-%m-%d")
        payload = {
            "formValues": {
                "Section 1": {
                    "uprnPWB": {"value": address.need("uprn")},
                    "minDate": {"value": min_date},
                    "maxDate": {"value": max_date},
                    "tokenString": {"value": token_string},
                }
            }
        }

        schedule_request = await http.post(
            f"{_BASE}?id=609d41ca89251&repeat_against=&noRetry=true&getOnlyTokens=undefined"
            f"&log_id=&app_name=AF-Renderer::Self&_={timestamp}&sid={sid}",
            json=payload,
        )

        rowdata = json.loads(schedule_request.content)["data"]
        html_rowdata = ET.fromstring(rowdata)[0][0][1][0][0].text
        rowdata = soup(html_rowdata)
        datedata = rowdata.find_all("h3")
        bindata = rowdata.find_all("ul")

        collections = []
        for index, item in enumerate(bindata):
            bin_date = datedata[index].text.strip()
            for bin_name in item.find_all("span"):
                collections.append(
                    Collection(
                        datetime.strptime(bin_date, "%A %d %B %Y").date(),
                        bin_name.text.strip(),
                    )
                )

        return collections


SCRAPER = ReigateAndBanstead()
