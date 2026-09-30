"""Solihull: look up a UPRN on the bin calendar and optionally predict later collections."""

from __future__ import annotations

from datetime import datetime, timedelta

from bs4 import Tag

from api.councils._base import Address, Collection, Http, Meta, Scraper, soup, text_of

_API_URL = "https://digital.solihull.gov.uk/BinCollectionCalendar/Calendar.aspx"


class Solihull(Scraper):
    meta = Meta(
        title="Solihull Council",
        url="https://www.solihull.gov.uk/",
        lads=("E08000029",),
        cases={
            "100070994046": {"uprn": "100070994046"},
            "200003821723, Predict": {"uprn": "200003821723", "predict": "true"},
            "New Garden Waste Subscription Service": {"uprn": "100071011936"},
        },
    )
    requires = frozenset({"uprn"})

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        r = await http.get(_API_URL, params={"UPRN": address.need("uprn")})
        page = soup(r.text)
        predict = (address.get("predict") or "").lower() == "true"

        entries: list[Collection] = []
        for card in page.find_all("div", class_="card-title"):
            bin_type_tag = card.find("h5") or card.find("h4")
            bin_type = text_of(bin_type_tag)

            for sibling in card.find_next_siblings("div", class_="mt-1"):
                date_tag = sibling.find("strong")
                if not date_tag:
                    continue
                date_str = date_tag.text
                try:
                    collection_date = datetime.strptime(date_str, "%A, %d %B %Y").date()
                except ValueError:
                    continue

                entries.append(Collection(collection_date, bin_type))

                if "next" not in sibling.text or not predict:
                    continue

                frequency_card = card.find_next_sibling()
                if not isinstance(frequency_card, Tag):
                    continue

                frequency_text = frequency_card.text.lower()
                if "every other week" in frequency_text:
                    frequency = 2
                elif "every week" in frequency_text:
                    frequency = 1
                else:
                    continue

                for i in range(1, 10 // frequency):
                    entries.append(
                        Collection(
                            collection_date + timedelta(weeks=i * frequency),
                            bin_type,
                        )
                    )

        return entries


SCRAPER = Solihull()
