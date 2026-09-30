"""Lewes: EnvironmentFirst bin lookup by UPRN, with a legacy URL fallback."""

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

_URL = "https://environmentfirst.co.uk/house.php"
_DATE_PATTERN = re.compile(r"(\d{1,2}(?:st|nd|rd|th)?\s+[A-Za-z]+\s+\d{4})")
_ORDINAL_PATTERN = re.compile(r"(?<=\d)(st|nd|rd|th)\b", re.IGNORECASE)


class Lewes(Scraper):
    meta = Meta(
        title="Lewes",
        url="https://www.lewes-eastbourne.gov.uk/article/1158/When-is-my-bin-collection-day",
        lads=("E07000063",),
        cases={},
    )
    requires = frozenset()

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        if address.uprn:
            url = f"{_URL}?uprn={address.uprn}"
        elif legacy_url := address.get("url"):
            url = legacy_url
        else:
            raise InputError("Lewes needs a UPRN or a URL")

        response = await http.get(url)
        if "mysqli_sql_exception" in response.text or "Fatal error" in response.text:
            raise UpstreamError(
                "EnvironmentFirst's bin lookup service is returning a server error "
                "(their database is unreachable)"
            )

        page = soup(response.text)
        collect_div = page.find("div", {"class": "collect"})
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


SCRAPER = Lewes()
