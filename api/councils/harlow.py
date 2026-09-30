"""Harlow: looks up upcoming collections from the council's UPRN-keyed API."""

from __future__ import annotations

from datetime import datetime

from api.councils._base import Address, Collection, Http, Meta, Scraper, soup

API_URL = (
    "https://selfserve.harlow.gov.uk/appshost/firmstep/self/apps/custompage/"
    "bincollectionsecho?uprn={uprn}"
)


class Harlow(Scraper):
    meta = Meta(
        title="Harlow Council",
        url="https://www.harlow.gov.uk",
        lads=("E07000073",),
        cases={
            "12 Kingfisher Gate, Old Harlow": {"uprn": "10033891501"},
            "4 Ryecroft, Harlow": {"uprn": "100090544008"},
            "2 The Crescent, Harlow": {"uprn": "100090546627"},
        },
    )
    requires = frozenset({"uprn"})

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        r = await http.get(API_URL.format(uprn=address.need("uprn")))
        entries = []

        for row in soup(r.text).find_all("div", {"class": "row collectionsrow"}):
            fields = row.findChildren()
            if (
                fields[0].text.strip()
                == "Please select an address to view the upcoming collections."
            ):
                continue

            entries.append(
                Collection(
                    datetime.strptime(fields[3].text, "%a - %d %b %Y\n").date(),
                    fields[2].text,
                )
            )

        return entries


SCRAPER = Harlow()
