"""North Somerset: POST a UPRN and postcode to the collection schedule form."""

from __future__ import annotations

from api.councils._base import (
    Address,
    Collection,
    Http,
    Meta,
    Scraper,
    UpstreamError,
    parse_date,
    soup,
)


class NorthSomerset(Scraper):
    meta = Meta(
        title="North Somerset Council",
        url="https://www.n-somerset.gov.uk",
        lads=("E06000024",),
        cases={
            "Walliscote Grove Road, Weston super Mare": {
                "uprn": "24009468",
                "postcode": "BS23 1UJ",
            },
            "Walliscote Road, Weston super Mare": {
                "uprn": "24136727",
                "postcode": "BS23 1EF",
            },
        },
    )
    requires = frozenset({"uprn", "postcode"})

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        response = await http.post(
            "https://forms.n-somerset.gov.uk/Waste/CollectionSchedule",
            data={
                "PreviousHouse": "",
                "PreviousPostcode": "-",
                "Postcode": address.need("postcode"),
                "SelectedUprn": address.need("uprn"),
            },
        )

        table = soup(response.text).table
        if table is None:
            raise UpstreamError("North Somerset collection schedule has no table")

        fields: list[str] = []
        table_data: list[dict[str, str]] = []

        for tr in table.find_all("tr"):
            for th in tr.find_all("th"):
                fields.append(th.text)

        for tr in table.find_all("tr"):
            datum: dict[str, str] = {}
            for i, td in enumerate(tr.find_all("td")):
                datum[fields[i]] = td.text
            if datum:
                table_data.append(datum)

        entries: list[Collection] = []
        for collection in table_data:
            for day in [
                collection["Next collection date"],
                collection.get("Following collection date"),
            ]:
                if not day:
                    continue  # no following collection listed
                entries.append(Collection(parse_date(day), collection["Service"]))

        return entries


SCRAPER = NorthSomerset()
