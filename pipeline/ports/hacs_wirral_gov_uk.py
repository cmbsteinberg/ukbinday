from datetime import datetime

import httpx
from bs4 import BeautifulSoup

from api.compat.hacs import Collection, Icons  # type: ignore[attr-defined]
from api.compat.hacs.exceptions import SourceArgumentNotFound

TITLE = "Wirral Council"
DESCRIPTION = "Source for wirral.gov.uk services for Wirral Council, UK."
URL = "https://wirral.gov.uk"
TEST_CASES = {
    "Elm Avenue, Upton": {
        "postcode": "CH49 4NP",
        "uprn": "000042037487",
    },
}
ICON_MAP = {
    "Green non-recyclable": Icons.GENERAL_WASTE,
    "Grey recycling": Icons.RECYCLING,
    "Grey food waste": Icons.BIO_KITCHEN,
    "Brown garden waste": Icons.GARDEN,
}

HOW_TO_GET_ARGUMENTS_DESCRIPTION = {
    "en": (
        "Go to https://www.wirral.gov.uk/bins-and-recycling/bin-collection-dates, "
        "enter your postcode and select your address. The number at the end of "
        "the resulting page URL (.../view/<number>) is your UPRN."
    ),
}

PARAM_DESCRIPTIONS = {
    "en": {
        "uprn": "The UPRN of your property, e.g. 42037487.",
    }
}

PARAM_TRANSLATIONS = {
    "en": {
        "uprn": "UPRN",
    }
}

VIEW_URL = "https://www.wirral.gov.uk/bins-and-recycling/bin-collection-dates/view/{}"


class Source:
    def __init__(self, uprn: str | int, postcode: str | None = None):
        # Wirral stores UPRNs without zero padding.
        self._uprn = str(uprn).strip().lstrip("0")

    async def fetch(self) -> list[Collection]:
        async with httpx.AsyncClient(follow_redirects=True, timeout=30) as session:
            r = await session.get(VIEW_URL.format(self._uprn))
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")

        entries = []
        for day in soup.select("li.waste-collection__day"):
            time_el = day.select_one("time")
            type_el = day.select_one(".waste-collection__day--type")
            if not time_el or not type_el:
                continue
            bin_type = type_el.get_text(strip=True)
            entries.append(
                Collection(
                    date=datetime.strptime(time_el["datetime"], "%d-%m-%Y").date(),
                    t=bin_type,
                    icon=ICON_MAP.get(bin_type),
                )
            )

        if not entries:
            # Unknown UPRNs render the page shell with no schedule.
            raise SourceArgumentNotFound("uprn", self._uprn)

        return entries
