"""Barnsley: POST the postcode and UPRN to its address-selection form and parse the collection dates."""

from __future__ import annotations

from datetime import date, datetime

from api.councils._base import (
    Address,
    Collection,
    Http,
    Meta,
    Scraper,
    UpstreamError,
    find_tag,
    soup,
)

_URL = "https://waste.barnsley.gov.uk/ViewCollection/SelectAddress"

_REQUEST_HEADERS = {
    "authority": "waste.barnsley.gov.uk",
    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
    "accept-language": "en-GB,en;q=0.9",
    "cache-control": "no-cache",
    "content-type": "application/x-www-form-urlencoded",
    "origin": "https://waste.barnsley.gov.uk",
    "pragma": "no-cache",
    "referer": "https://waste.barnsley.gov.uk/ViewCollection/SelectAddress",
    "sec-ch-ua": '"Chromium";v="118", "Opera GX";v="104", "Not=A?Brand";v="99"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "sec-fetch-dest": "document",
    "sec-fetch-mode": "navigate",
    "sec-fetch-site": "same-origin",
    "sec-fetch-user": "?1",
    "upgrade-insecure-requests": "1",
}


def _parse_date(value: str) -> date:
    if value.lower() == "today":
        return datetime.now().date()
    return datetime.strptime(value, "%A, %B %d, %Y").date()


class Barnsley(Scraper):
    meta = Meta(
        title="Barnsley Metropolitan Borough Council",
        url="https://barnsley.gov.uk",
        lads=("E08000016",),
        cases={
            "S71 1EE 100050671689": {"postcode": "S71 1EE", "uprn": "100050671689"},
            "S75 1QF 10032783992": {"postcode": "S75 1QF", "uprn": "10032783992"},
            "test": {"postcode": "S70 3QU", "uprn": "100050607581"},
        },
    )
    requires = frozenset({"postcode", "uprn"})
    headers = {
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.5993.118 Safari/537.36"
    }

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        response = await http.post(
            _URL,
            headers=_REQUEST_HEADERS,
            data={
                "personInfo.person1.HouseNumberOrName": "",
                "personInfo.person1.Postcode": address.need("postcode"),
                "personInfo.person1.UPRN": address.need("uprn"),
                "person1_SelectAddress": "Select address",
            },
            check=False,
        )
        page = soup(response.text)

        if response.status_code != 200:
            raise UpstreamError("Error getting results from website")

        results = find_tag(page, "div", {"class": "panel"}).find_all("fieldset")[0:2]
        heading = results[0].find_all("p")[1:3]

        collections = []
        for bin_name in heading[1].text.strip().split(", "):
            collections.append(
                Collection(
                    _parse_date(heading[0].text),
                    bin_name + " bin",
                )
            )

        results_table = [row for row in results[1].find_all("tbody")[0] if row != "\n"]
        for row in results_table:
            text_list = [item.text.strip() for item in row.contents if item != "\n"]
            for bin_name in text_list[1].split(", "):
                collections.append(
                    Collection(
                        _parse_date(text_list[0]),
                        bin_name + " bin",
                    )
                )

        return collections


SCRAPER = Barnsley()
