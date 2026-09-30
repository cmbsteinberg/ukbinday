import datetime
import re

import httpx
from bs4 import BeautifulSoup

from api.compat.hacs import Collection, Icons  # type: ignore[attr-defined]
from api.compat.hacs.exceptions import (
    SourceArgumentNotFound,
    SourceArgumentRequired,
)

TITLE = "Uttlesford District Council"
DESCRIPTION = "Source for uttlesford.gov.uk, Uttlesford District Council, UK"
URL = "https://www.uttlesford.gov.uk"
TEST_CASES = {
    "Brook Cottage, CM6 1LW": {"house": "29142-Tuesday"},
    "Springfields, CM6 1BP": {"house": "26455-Thursday"},
}

API_URL = "https://bins.uttlesford.gov.uk/collections.php?house={house}"
ADDRESS_URL = "https://bins.uttlesford.gov.uk/result.php?postcode={postcode}"

ICON_MAP = {
    "black": Icons.GENERAL_WASTE,
    "green": Icons.RECYCLING,
    "brown": Icons.BIO_KITCHEN,
}

PICTURE_MAP = {
    "black": "https://bins.uttlesford.gov.uk/img/result-black.png",
    "green": "https://bins.uttlesford.gov.uk/img/result-green.png",
    "brown": "https://bins.uttlesford.gov.uk/img/result-brown.png",
}

TEXT_MAP = {
    "black": "Black (Non-Recyclable)",
    "green": "Green (Dry Recycling)",
    "brown": "Brown (Food Waste)",
}


class Source:
    def __init__(self, house=None, postcode=None, house_number=None, street=None):
        self._house = house
        self._postcode = postcode
        self._house_number = house_number
        self._street = street

    async def _resolve_house(self, client):
        """Look up the '<id>-<Day>' house value from postcode + house number/street."""
        if not (self._postcode and self._house_number):
            raise SourceArgumentRequired(
                "house", "or both postcode and house_number must be provided"
            )
        postcode = re.sub(r"\s+", "", self._postcode).upper()
        r = await client.get(ADDRESS_URL.format(postcode=postcode))
        r.raise_for_status()
        options = BeautifulSoup(r.text, "html.parser").find_all("option")

        number = self._house_number.strip().lower()
        street = (self._street or "").strip().lower()
        wanted = f"{number}, {street}" if street else None
        prefix_match = None
        for opt in options:
            value = opt.get("value")
            if not value:
                continue
            text = " ".join(opt.get_text().split()).lower()
            if wanted and text == wanted:
                return value
            if prefix_match is None and text.startswith(number + ","):
                prefix_match = value
        if prefix_match:
            return prefix_match
        raise SourceArgumentNotFound("house_number", self._house_number)

    async def fetch(self):
        client = httpx.AsyncClient(follow_redirects=True)
        house = self._house or await self._resolve_house(client)
        q = str(API_URL).format(house=house)

        r = await client.get(q)
        r.raise_for_status()

        def trimsuffix(s):
            return re.sub(r"(\d)(st|nd|rd|th)", r"\1", s)

        responseContent = r.text

        today = datetime.date.today()

        entries = []

        soup = BeautifulSoup(responseContent, "html.parser")
        table = soup.findAll("table")

        rows = table[1].findAll(lambda tag: tag.name == "tr")

        for row in rows:
            fields = row.findChildren()
            image = row.find("img")
            datestr = fields[3].text
            datestr = trimsuffix(datestr) + " " + today.strftime("%Y")
            date = datetime.datetime.strptime(datestr, "%A %d %B %Y")

            # As they don't show the year we need to check if it should actually be next year
            if date.date() < today:
                date = date.replace(year=today.year + 1)

            # As all the image alt text etc is wrong on the website we have to go by the image itself
            if "green" in image["src"]:
                collectiontxt = "green"
            else:
                collectiontxt = "black"

            entries.append(
                Collection(
                    date=date.date(),
                    t=TEXT_MAP.get(collectiontxt),
                    picture=PICTURE_MAP.get(collectiontxt),
                    icon=ICON_MAP.get(collectiontxt),
                )
            )
            # Add a second collection entry as all collections include the brown food bin
            collectiontxt = "brown"
            entries.append(
                Collection(
                    date=date.date(),
                    t=TEXT_MAP.get(collectiontxt),
                    picture=PICTURE_MAP.get(collectiontxt),
                    icon=ICON_MAP.get(collectiontxt),
                )
            )

        return entries
