"""Huntingdonshire: looks up collection dates by UPRN from its waste calendar API."""

from __future__ import annotations

from datetime import datetime

from api.councils._base import Address, Collection, Http, Meta, Scraper

API = "https://servicelayer3c.azure-api.net/wastecalendar/collection/search"


class Huntingdonshire(Scraper):
    meta = Meta(
        title="Huntingdonshire District Council",
        url="https://www.huntingdonshire.gov.uk",
        lads=("E07000011",),
        cases={
            "Wells Close, Brampton": {"uprn": "100090123510"},
            "Inkerman Rise, St. Neots": {"uprn": "10000144271"},
        },
    )
    requires = frozenset({"uprn"})

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        r = await http.get(
            f"{API}/{address.need('uprn')}",
            params={"authority": "HDC", "take": 20},
        )
        collections = r.json()["collections"]
        entries = []
        for collection in collections:
            for round_type in collection["roundTypes"]:
                entries.append(
                    Collection(
                        datetime.strptime(collection["date"], "%Y-%m-%dT%H:%M:%SZ").date(),
                        round_type.title(),
                    )
                )
        return entries


SCRAPER = Huntingdonshire()
