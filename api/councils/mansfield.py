"""Mansfield: looks up collections from the WhiteSpace service using the UPRN and current date."""

from __future__ import annotations

from datetime import datetime

from api.councils._base import Address, Collection, Http, Meta, Scraper

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:109.0) Gecko/20100101 Firefox/117.0",
    "Host": "portal.wokingham.gov.uk",
    "Origin": "https://www.mansfield.gov.uk",
    "Referer": "https://www.mansfield.gov.uk/",
}
ENDPOINT = "https://portal.mansfield.gov.uk/MDCWhiteSpaceWebService/WhiteSpaceWS.asmx/GetCollectionByUPRNAndDate"


class Mansfield(Scraper):
    meta = Meta(
        title="Mansfield District Council",
        url="https://mansfield.gov.uk",
        lads=("E07000174",),
        cases={
            "Test_001": {"uprn": "10091487039"},
            "Test_002": {"uprn": "100031399527"},
            "Test_003": {"uprn": "200000666900"},
        },
    )
    requires = frozenset({"uprn"})
    headers = HEADERS

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        coldate = datetime.strftime(datetime.now(), "%d/%m/%Y")
        r = await http.get(
            f"{ENDPOINT}?apiKey=mDc-wN3-B0f-f4P&UPRN={address.need('uprn')}&coldate={coldate}"
        )
        json_data = r.json()["Collections"]

        entries = []
        for item in json_data:
            entries.append(
                Collection(
                    date=datetime.strptime(item["Date"], "%d/%m/%Y %H:%M:%S").date(),
                    type=item["Service"].split(" ")[0],
                )
            )

        return entries


SCRAPER = Mansfield()
