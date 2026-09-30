"""Stoke-on-Trent: looks up a UPRN in the council's XML bin calendar."""

from datetime import datetime

from bs4 import BeautifulSoup

from api.councils._base import Address, Collection, Http, Meta, Scraper, UpstreamError

_API_URL = (
    "https://www.stoke.gov.uk/jadu/custom/webserviceLookUps/"
    "BarTecWebServices_missed_bin_calendar.php?UPRN="
)
_DATE_FORMAT = "%d/%m/%Y"
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.5",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "same-origin",
}


class StokeOnTrent(Scraper):
    meta = Meta(
        title="Stoke-on-Trent",
        url="https://www.stoke.gov.uk/",
        lads=("E06000021",),
        cases={
            "Test1": {"uprn": "3455011383"},
            "Test2": {"uprn": "3455011391"},
        },
    )
    requires = frozenset({"uprn"})
    headers = _HEADERS

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        uprn = address.need("uprn").zfill(12)
        r = await http.get(_API_URL + uprn, check=False)

        if r.status_code == 403 or "403 Client Error" in r.text:
            raise UpstreamError("Rate limiting or IP ban may be in effect")

        document = BeautifulSoup(r.text, features="xml")
        collections = []

        for bin_round in document.find_all("BinRound"):
            bin_name = bin_round.find("Bin").text
            date_time = bin_round.find("DateTime").text.split(" ")[0]
            day = datetime.strptime(date_time, _DATE_FORMAT).date()
            collections.append(Collection(day, bin_name))

        return collections


SCRAPER = StokeOnTrent()
