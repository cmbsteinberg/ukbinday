import logging
from datetime import datetime

import httpx
from bs4 import BeautifulSoup

from api.compat.hacs import Collection, Icons
from api.compat.hacs.exceptions import (
    SourceArgumentNotFound,
    SourceArgumentNotFoundWithSuggestions,
)

TITLE = "Herefordshire City Council"
DESCRIPTION = "Source for herefordshire.gov.uk services for hereford"
URL = "https://herefordshire.gov.uk"
TEST_CASES = {
    "houseNumber": {"postcode": "hr49js", "house_number": "52"},
    "uprn": {"postcode": "hr49js", "house_number": "200002607460"},
}

PARAM_DESCRIPTIONS = {
    "en": {
        "postcode": "Postcode of the property, e.g. HR4 9JS",
        "house_number": (
            "House house_number, house name, or UPRN (Unique Property Reference "
            "Number) of the property. If your property only has a name and "
            "no house_number, enter the name; if it is still not found, the error "
            "message will list the full addresses found for your postcode "
            "so you can copy the UPRN or exact wording from there."
        ),
    },
}

PARAM_TRANSLATIONS = {
    "en": {
        "postcode": "Postcode",
        "house_number": "House Number / Name / UPRN",
    },
}

API_URLS = {
    "address_search": "https://trsewmllv7.execute-api.eu-west-2.amazonaws.com/dev/address",
    "collection": "https://www.herefordshire.gov.uk/rubbish-recycling/check-bin-collection-day",  # ?blpu_uprn=200002607454",
}
HEADER = {"user-agent": "Mozilla/5.0"}
ICON_MAP = {
    "General": Icons.GENERAL_WASTE,
    "Recycling": Icons.RECYCLING,
    "Garden": Icons.GARDEN,
}

_LOGGER = logging.getLogger(__name__)


class Source:
    def __init__(self, postcode: str, house_number: str):
        self._postcode = postcode
        # keep the value exactly as entered (only trim whitespace) so error
        # messages show the user's own input; all matching below is done
        # case-insensitively.
        self._house_number = str(house_number).strip()

    async def fetch(self):
        # fetch location id
        r = await httpx.AsyncClient(follow_redirects=True).get(
            API_URLS["address_search"],
            headers=HEADER,
            params={"postcode": self._postcode, "type": "standard"},
        )
        r.raise_for_status()
        addresses = r.json()
        if (
            (addresses.get("error"))
            or "results" not in addresses
            or len(addresses["results"]) == 0
        ):
            raise SourceArgumentNotFound("postcode", self._postcode)

        results = addresses["results"]

        # `house_number` may be a classic house house_number (PAO_START_NUMBER), a house
        # name (PAO_TEXT for named properties, or SAO_TEXT for named
        # sub-units such as flats), or the property's UPRN directly -
        # accepting the UPRN lets users bypass name/house_number matching entirely
        # when they already know it (e.g. from findmyaddress.co.uk).
        target = self._house_number.lower()

        def matches_exact(lpi: dict) -> bool:
            for field in ("UPRN", "PAO_TEXT", "PAO_START_NUMBER", "SAO_TEXT"):
                value = lpi.get(field)
                if value is not None and str(value).strip().lower() == target:
                    return True
            return False

        address_ids = [x for x in results if matches_exact(x["LPI"])]

        # Fall back to a substring match against the full address string.
        # This helps house-name-only properties whose name is not cleanly
        # isolated into PAO_TEXT/SAO_TEXT (e.g. extra punctuation/spacing).
        if not address_ids and len(target) >= 3:
            address_ids = [
                x
                for x in results
                if x["LPI"].get("ADDRESS")
                and target in str(x["LPI"]["ADDRESS"]).lower()
            ]

        if len(address_ids) == 0:
            # Show the full address strings (rather than bare fragments) so
            # users without a house house_number can identify their property and
            # either enter its house name verbatim or its UPRN instead.
            suggestions = sorted(
                {
                    x["LPI"]["ADDRESS"]
                    for x in results
                    if x["LPI"].get("ADDRESS") is not None
                }
            )
            raise SourceArgumentNotFoundWithSuggestions(
                "house_number", self._house_number, suggestions
            )

        q = str(API_URLS["collection"])
        r = await httpx.AsyncClient(follow_redirects=True).get(
            q, headers=HEADER, params={"blpu_uprn": address_ids[0]["LPI"]["UPRN"]}
        )
        r.raise_for_status()

        # --- Updated DOM parsing (site changed) ---
        soup = BeautifulSoup(r.text, "html.parser")
        container = soup.find(id="binCollectionDetails")
        if not container:
            # fall back to legacy wrapper if council reverts
            legacy = soup.find(id="wasteCollectionDates")
            if not legacy:
                raise Exception(
                    "Could not find bin collection section on the council page (IDs changed)."
                )
            container = legacy

        # Extract first <li> date under each heading
        def first_li_after_heading(heading_keyword: str) -> list[str]:
            # find <h3> that contains the keyword, then take first <li> in the next <ul>
            resulsts = []
            for h3 in container.find_all("h3"):
                title = h3.get_text(strip=True).lower()
                if heading_keyword.lower() in title:
                    ul = h3.find_next_sibling("ul")
                    if ul:
                        lis = ul.find_all("li")
                        for li in lis:
                            # strip any "(next collection)" etc.
                            text = li.get_text(strip=True)
                            cut = text.find("(")
                            resulsts.append(
                                text[:cut].strip() if cut != -1 else text.strip()
                            )
            return resulsts

        sections = (
            ("General", "General rubbish", first_li_after_heading("general rubbish")),
            ("Recycling", "Recycling", first_li_after_heading("recycling")),
            ("Garden", "Garden", first_li_after_heading("garden waste")),
        )

        entries = []
        for icon_key, waste_type, date_strs in sections:
            for date_str in date_strs:
                try:
                    date = datetime.strptime(date_str, "%A %d %B %Y").date()
                except ValueError:
                    # Not every heading lists dates. Properties without a garden
                    # waste subscription get a link to the calendar instead, so
                    # skip anything that is not a date rather than failing.
                    _LOGGER.debug(
                        "Skipping non-date entry under %s: %r", waste_type, date_str
                    )
                    continue
                entries.append(
                    Collection(
                        date=date,
                        t=waste_type,
                        icon=ICON_MAP[icon_key],
                    ),
                )
        if not entries:
            raise Exception(
                "No collection dates found for this address, make sure there are any concrete collection dates listed on the website for this address."
            )

        return entries
