"""Horsham: submit the property's UPRN to the council's refuse calendar endpoint."""

from __future__ import annotations

from datetime import datetime

from api.councils._base import Address, Collection, Http, Meta, Scraper, Transport, soup

_API_URL = "https://satellite.horsham.gov.uk/environment/refuse/cal_details.asp"


class Horsham(Scraper):
    meta = Meta(
        title="Horsham District Council",
        url="https://www.horsham.gov.uk",
        lads=("E07000227",),
        cases={
            "Blackthorn Avenue - number": {"uprn": "10013792881"},
            "Blackthorn Avenue - string": {"uprn": "10013792881"},
        },
    )
    requires = frozenset({"uprn"})
    # Legacy TLS 1.2 cipher only; curl copes, default httpx cannot negotiate it.
    transport = Transport.CURL_CFFI

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        r = await http.post(_API_URL, data={"uprn": address.need("uprn")})
        results = soup(r.text).find_all("tr")

        collections = []
        for result in results:
            result_row = result.find_all("td")
            if len(result_row) == 0:
                continue
            day = datetime.strptime(result_row[1].text, "%d/%m/%Y").date()

            list_items = result_row[2].find_all("li")
            collection_items = [li.get_text(strip=True) for li in list_items]
            for collection_type in collection_items:
                if not collection_type:
                    continue
                collections.append(Collection(day, collection_type))

        return collections


SCRAPER = Horsham()
