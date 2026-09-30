"""Adur & Worthing: one shared bin-day page for both councils.

The page takes the UPRN directly as `brlu-selected-address`. Without a UPRN
we search the postcode and pick the property from the returned <select>.
Dates are listed without a year ("Thursday 1st October").
"""

from __future__ import annotations

from api.councils._base import (
    Address,
    Collection,
    Http,
    InputError,
    Meta,
    Scraper,
    match_address,
    parse_date,
    soup,
    text_of,
)

PAGE = "https://www.adur-worthing.gov.uk/bin-day/"


class AdurAndWorthing(Scraper):
    meta = Meta(
        title="Adur & Worthing Councils",
        url="https://www.adur-worthing.gov.uk/bin-day/",
        lads=("E07000223", "E07000229"),
        cases={
            "Test_001": {"postcode": "BN15 9UX", "house_number": "1", "street": "Western Road North"},
            "Test_002": {"postcode": "BN43 5WE", "house_number": "6", "street": "Hebe Road"},
            "Test_003": {"uprn": "100062209109"},
        },
    )
    requires = frozenset()  # the UPRN alone, or a postcode plus the address text

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        uprn = address.uprn
        if uprn is None:
            if address.postcode is None:
                raise InputError("Adur & Worthing needs a UPRN or a postcode")
            r = await http.get(
                PAGE,
                params={"brlu-address-postcode": address.postcode, "return-url": "/bin-day/", "action": "search"},
            )
            options = soup(r.text).select("select#brlu-selected-address option[value]")
            uprn = match_address(address, options, text=text_of, uprn=lambda o: o["value"])["value"]

        r = await http.get(PAGE, params={"brlu-selected-address": uprn, "return-url": "/bin-day/"})
        collections = []
        for row in soup(r.text).select("div.bin-collection-listing-row"):
            bin_type = text_of(row.find("h2"))
            if bin_type == "General rubbish":
                bin_type = "Refuse"
            elif bin_type.startswith("Garden waste"):
                bin_type = "Garden"
            for strong in row.find_all("strong"):
                if "Next collection" not in strong.get_text():
                    continue
                # "Next collection dates:" followed by <br/>-separated dates.
                for line in strong.parent.find_all(string=True):
                    text = line.strip()
                    if not text or text == strong.get_text().strip():
                        continue
                    try:
                        collections.append(Collection(parse_date(text), bin_type))
                    except ValueError:
                        continue
        return collections


SCRAPER = AdurAndWorthing()
