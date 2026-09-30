"""Derby: look up bin collections by UPRN on the council's bin-day page."""

from __future__ import annotations

import logging
from datetime import datetime

from api.councils._base import Address, Collection, Http, Meta, Scraper, soup, text_of

_LOGGER = logging.getLogger(__name__)
_BASE = "https://secure.derby.gov.uk/binday/Bindays"


class Derby(Scraper):
    meta = Meta(
        title="Derby City Council",
        url="https://derby.gov.uk",
        lads=("E06000015",),
        cases={
            "22A Wood Road, Chaddesden, Derby, DE21 4LU": {"uprn": "10010688168"},
            "Allestree Home Improvements, 512 Duffield Road, Derby, DE22 2DL": {
                "uprn": "100030310335"
            },
        },
    )
    requires = frozenset({"uprn"})

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        r = await http.get(f"{_BASE}/{address.need('uprn')}")
        results = soup(r.text).find_all("div", {"class": "binresult"})

        collections = []
        for result in results:
            date_node = result.find("strong")
            try:
                day = datetime.strptime(text_of(date_node), "%A, %d %B %Y:").date()
            except ValueError:
                _LOGGER.info("Skipped %s as it does not match time format", date_node)
                continue
            img_tag = result.find("img")
            collections.append(Collection(day, img_tag["alt"]))
        return collections


SCRAPER = Derby()
