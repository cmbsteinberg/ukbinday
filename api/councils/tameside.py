"""Tameside: submit the UPRN and compact postcode to the bin-dates form."""

from __future__ import annotations

import re
from datetime import datetime

from api.councils._base import (
    Address,
    Collection,
    Http,
    Meta,
    Scraper,
    find_tag,
    soup,
)

_API_URL = "https://public.tameside.gov.uk/forms/bin-dates.asp"
_REGEX = r"(st|nd|rd|th)"


class Tameside(Scraper):
    meta = Meta(
        title="Tameside Metropolitan Borough Council",
        url="https://www.tameside.gov.uk",
        lads=("E08000008",),
        cases={
            "Test_001": {"postcode": "M34 6AG", "uprn": "100011601683"},
            "Test_002": {"postcode": "OL5 9JL", "uprn": "100011548952"},
            "Test_003": {"postcode": "SK14 8JP", "uprn": "100011573345"},
        },
    )
    requires = frozenset({"postcode", "uprn"})
    headers = {
        "user-agent": "Mozilla/5.0 (X11; Linux x86_64; rv:109.0) Gecko/20100101 Firefox/117.0",
        "origin": "https://public.tameside.gov.uk",
        "referrer": "https://public.tameside.gov.uk/forms/bin-dates.asp",
    }

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        postcode = address.need("postcode").upper().strip().replace(" ", "")
        uprn = address.need("uprn")

        await http.get(_API_URL)

        payload = {
            "F03_I01_SelectAddress": f"{uprn}-{postcode}",
            "AdvanceSearch": "Continue",
            "F01_I02_Postcode": postcode,
            "F01_I03_Street": "",
            "F01_I04_Town": "",
            "history": ",1,3,",
        }
        r = await http.post(_API_URL, data=payload)
        page = soup(r.text)

        collections = []
        for year in page.find_all("fieldset", {"class": "year"}):
            year_text = find_tag(year, "h3").text

            for month in year.find_all("tr", {"class": "month"}):
                month_text = find_tag(month, "td", {"class": "month"}).text

                for day in month.find_all("td", {"class": "day"}):
                    day_text = re.sub(_REGEX, "", day.text)
                    collection_date = datetime.strptime(
                        day_text + month_text + year_text, "%d%B%Y"
                    ).date()

                    for bin_image in day.find_all("img", alt=True):
                        bin_type = bin_image.get("alt").replace("_Icon", "").replace("_", " ")
                        collections.append(Collection(collection_date, bin_type))

        return collections


SCRAPER = Tameside()
