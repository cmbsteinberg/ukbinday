"""Gedling: query the bin calendar API using the house number and/or postcode."""

from __future__ import annotations

from datetime import datetime

from api.councils._base import Address, Collection, Http, InputError, Meta, Scraper

_API_URL = "https://api.gbcbincalendars.co.uk/get-bin-collection-calendar"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/134.0.0.0 Safari/537.36"
    ),
}


class Gedling(Scraper):
    meta = Meta(
        title="Gedling",
        url="https://waste.digital.gedling.gov.uk/w/webpage/bin-collections",
        lads=("E07000173",),
        cases={},
    )
    requires = frozenset()

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        house_number = address.house_number
        postcode = address.postcode

        if house_number and postcode:
            address_query = f"{house_number} {postcode}"
        elif postcode:
            address_query = postcode
        elif house_number:
            address_query = house_number
        else:
            raise InputError(
                "Supply a postcode, or house number + postcode, to look up "
                "your Gedling bin collection schedule."
            )

        response = await http.get(
            _API_URL,
            params={"address": address_query},
            headers=_HEADERS,
            timeout=30,
        )
        result = response.json()
        if not result.get("collections"):
            return []

        run_date = datetime.now().date()
        collections = []
        for month_block in result["collections"]:
            for entry in month_block.get("dates", []):
                bin_date = datetime.strptime(entry["date"], "%Y-%m-%d").date()
                if bin_date < run_date:
                    continue
                for service in entry.get("collections", []):
                    collections.append(Collection(bin_date, service))
        return collections


SCRAPER = Gedling()
