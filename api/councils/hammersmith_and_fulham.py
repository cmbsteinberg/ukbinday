"""Hammersmith & Fulham: searches collections by postcode and returns the next weekday dates."""

from __future__ import annotations

from datetime import date

from api.councils._base import (
    Address,
    Collection,
    Http,
    Meta,
    Scraper,
    next_weekday,
    soup,
    weekday_number,
)

_URL = "https://www.lbhf.gov.uk/"
_RESULTS_URL = "https://www.lbhf.gov.uk/bin-recycling-day/results"
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36"
)


class HammersmithAndFulham(Scraper):
    meta = Meta(
        title="Hammersmith & Fulham",
        url=_URL,
        lads=("E09000013",),
        cases={},
    )
    requires = frozenset({"postcode"})
    headers = {"User-Agent": _USER_AGENT}

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        postcode = address.need("postcode").strip().replace(" ", "")
        response = await http.get(f"{_RESULTS_URL}?postcode={postcode}")
        results = soup(response.text).find("div", {"class": "nearest-search-results"})
        links = results.find("ol").find_all("a")

        today = date.today()
        collections = []
        for link in links:
            collection_day, collection_type = link.get_text().split(" - ")
            day_number = weekday_number(collection_day)
            collection_date = (
                today
                if day_number == today.weekday()
                else next_weekday(collection_day, after=today, include_today=False)
            )
            collections.append(Collection(collection_date, collection_type))

        return collections


SCRAPER = HammersmithAndFulham()
