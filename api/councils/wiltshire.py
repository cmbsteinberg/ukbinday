"""Wiltshire: requests seven months of collection data by UPRN and postcode."""

from __future__ import annotations

from datetime import date, datetime

from api.councils._base import Address, Collection, Http, Meta, Scraper, soup

_URL = "https://ilforms.wiltshire.gov.uk/wastecollectiondays/wastecollectioncalendar"
_COLLECTIONS = {
    "Household waste",
    "Mixed dry recycling (blue lidded bin)",
    "Mixed dry recycling (blue lidded bin) and glass (black box or basket)",
    "Chargeable garden waste",
}


def _add_month(day: date) -> date:
    if day.month < 12:
        return day.replace(month=day.month + 1)
    return day.replace(year=day.year + 1, month=1)


async def _fetch_month(
    http: Http, uprn: str, postcode: str, fetch_month: date
) -> list[Collection]:
    response = await http.post(
        _URL,
        params={
            "Postcode": postcode,
            "Uprn": uprn,
            "Month": fetch_month.month,
            "Year": fetch_month.year,
        },
    )

    page = soup(response.text)
    collections = []
    for collection in _COLLECTIONS:
        for tag in page.find_all(attrs={"data-original-title": collection}):
            collections.append(
                Collection(
                    datetime.strptime(
                        tag["data-original-datetext"], "%A %d %B, %Y"
                    ).date(),
                    collection,
                )
            )
    return collections


class Wiltshire(Scraper):
    meta = Meta(
        title="Wiltshire Council",
        url="https://wiltshire.gov.uk",
        lads=("E06000054",),
        cases={
            "standard_uprn": {"uprn": "100121085972", "postcode": "BA149QP"},
            "short_uprn": {"uprn": "10093279003", "postcode": "SN128FF"},
            "padded_uprn": {"uprn": "010093279003", "postcode": "SN128FF"},
        },
    )
    requires = frozenset({"uprn", "postcode"})

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        uprn = address.need("uprn").zfill(12)
        postcode = address.need("postcode")
        fetch_month = date.today().replace(day=1)

        collections = []
        for _ in range(7):
            collections.extend(await _fetch_month(http, uprn, postcode, fetch_month))
            fetch_month = _add_month(fetch_month)
        return collections


SCRAPER = Wiltshire()
