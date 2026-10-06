"""EnvironmentFirst bin lookup (`environmentfirst.co.uk/house.php?uprn=`), used by Eastbourne and Lewes.

`GET house.php?uprn=<uprn>` answers with a page whose `div.collect` holds one
paragraph per service: the service in the text, the date ("Monday 5th October
2026") in a `<strong>`. Old calendar subscriptions stored a full lookup URL
instead of a UPRN, so a `url` param is accepted when there is no UPRN.

Services are named "Rubbish", "Recycling" and "Garden", whatever the paragraph says.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

from api.councils._base import (
    Address,
    Collection,
    Http,
    InputError,
    Platform,
    UpstreamError,
    soup,
)

_DATE_PATTERN = re.compile(r"(\d{1,2}(?:st|nd|rd|th)?\s+[A-Za-z]+\s+\d{4})")
_ORDINAL_PATTERN = re.compile(r"(?<=\d)(st|nd|rd|th)\b", re.IGNORECASE)
_SERVICES = (("rubbish", "Rubbish"), ("recycling", "Recycling"), ("garden", "Garden"))


@dataclass(frozen=True, slots=True, kw_only=True)
class EnvironmentFirstConfig:
    lookup_url: str = "https://environmentfirst.co.uk/house.php"


class EnvironmentFirst(Platform[EnvironmentFirstConfig]):
    requires = frozenset()  # a UPRN, or a legacy lookup URL

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        if address.uprn:
            url = f"{self.config.lookup_url}?uprn={address.uprn}"
        elif legacy_url := address.get("url"):
            url = legacy_url
        else:
            raise InputError(f"{self.meta.title} needs a UPRN or a legacy lookup URL")

        response = await http.get(url)
        if "mysqli_sql_exception" in response.text or "Fatal error" in response.text:
            raise UpstreamError(
                "EnvironmentFirst's bin lookup service is returning a server error (their database is unreachable)"
            )

        collect_div = soup(response.text).find("div", {"class": "collect"})
        if collect_div is None:
            raise UpstreamError("EnvironmentFirst page has no collection section")

        collections: list[Collection] = []
        for paragraph in collect_div.find_all("p"):
            strong = paragraph.find("strong")
            if not strong:
                continue

            label = paragraph.get_text(" ", strip=True).lower()
            bin_type = next((name for key, name in _SERVICES if key in label), None)
            if bin_type is None:
                continue

            match = _DATE_PATTERN.search(strong.get_text(" ", strip=True))
            if not match:
                continue
            try:
                day = datetime.strptime(_ORDINAL_PATTERN.sub("", match.group(1)), "%d %B %Y").date()
            except ValueError:
                continue
            collections.append(Collection(day, bin_type))

        if not collections:
            raise UpstreamError("EnvironmentFirst page lists no readable collections")
        return collections
