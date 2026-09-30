"""Eastbourne: EnvironmentFirst lookup by UPRN, with a legacy URL fallback."""

from __future__ import annotations

import re
from datetime import datetime

from api.councils._base import (
    Address,
    Collection,
    Http,
    InputError,
    Meta,
    Scraper,
    UpstreamError,
    soup,
)

_DATE_PATTERN = re.compile(r"(\d{1,2}(?:st|nd|rd|th)?\s+[A-Za-z]+\s+\d{4})")
_ORDINAL_PATTERN = re.compile(r"(?<=\d)(st|nd|rd|th)\b")


class Eastbourne(Scraper):
    meta = Meta(
        title="Eastbourne",
        url="https://www.lewes-eastbourne.gov.uk/article/1158/When-is-my-bin-collection-day",
        lads=("E07000061",),
        cases={},
    )
    requires = frozenset()

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        uprn = address.uprn
        if uprn:
            url = f"https://environmentfirst.co.uk/house.php?uprn={uprn}"
        else:
            url = address.get("url")
            if not url:
                raise InputError("Eastbourne needs a UPRN or a legacy lookup URL")

        response = await http.get(url)
        if "mysqli_sql_exception" in response.text or "Fatal error" in response.text:
            raise UpstreamError(
                "EnvironmentFirst's bin lookup service is returning a server error "
                "(their database is unreachable)"
            )

        collect_div = soup(response.text).find("div", {"class": "collect"})
        if collect_div is None:
            return []

        collections: list[Collection] = []
        for paragraph in collect_div.find_all("p"):
            strong = paragraph.find("strong")
            if not strong:
                continue

            label = paragraph.get_text(" ", strip=True).lower()
            if "rubbish" in label:
                bin_type = "Rubbish"
            elif "recycling" in label:
                bin_type = "Recycling"
            elif "garden" in label:
                bin_type = "Garden"
            else:
                continue

            match = _DATE_PATTERN.search(strong.get_text(" ", strip=True))
            if not match:
                continue

            cleaned = _ORDINAL_PATTERN.sub("", match.group(1))
            try:
                collection_date = datetime.strptime(cleaned, "%d %B %Y").date()
            except ValueError:
                continue
            collections.append(Collection(collection_date, bin_type))

        return collections


SCRAPER = Eastbourne()
