"""Ashford: post the postcode and UPRN through the council's Web Forms lookup."""

from __future__ import annotations

import re
from datetime import datetime

from api.councils._base import (
    Address,
    AddressNotFound,
    Collection,
    Http,
    InputError,
    Meta,
    Scraper,
    soup,
)

_API_URL = "https://secure.ashford.gov.uk/waste/collectiondaylookup/"
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Application": "application/x-www-form-urlencoded",
}


class Ashford(Scraper):
    meta = Meta(
        title="Ashford Borough Council",
        url="https://ashford.gov.uk",
        lads=("E07000105",),
        cases={
            "100060796052": {"uprn": "100060796052", "postcode": "TN23 3DY"},
            "100060780440": {"uprn": "100060780440", "postcode": "TN24 9JD"},
            "100062558476": {"uprn": "100062558476", "postcode": "TN23 3LX"},
        },
    )
    requires = frozenset({"postcode", "uprn"})
    headers = _HEADERS
    verify_tls = False

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        postcode = address.need("postcode")
        uprn = address.need("uprn")

        r = await http.get(_API_URL)
        page = soup(r.text)

        args = {}
        for input_tag in page.find_all("input"):
            if not input_tag.get("name"):
                continue
            args[input_tag["name"]] = input_tag.get("value")
        args["ctl00$ContentPlaceHolder1$CollectionDayLookup2$HiddenField_UPRN"] = ""
        args["ctl00$ContentPlaceHolder1$CollectionDayLookup2$TextBox_PostCode"] = postcode
        args["ctl00$ContentPlaceHolder1$CollectionDayLookup2$Button_PostCodeSearch"] = "Continue+>"
        args["__EVENTTARGET"] = ""
        args["__EVENTARGUMENT"] = ""

        r = await http.post(_API_URL, data=args)
        page = soup(r.text)

        args = {}
        for input_tag in page.find_all("input"):
            if not input_tag.get("name"):
                continue
            args[input_tag["name"]] = input_tag.get("value")
        args["ctl00$ContentPlaceHolder1$CollectionDayLookup2$DropDownList_Addresses"] = uprn
        args["ctl00$ContentPlaceHolder1$CollectionDayLookup2$Button_PostCodeSearch"] = "Continue+>"
        del args["ctl00$ContentPlaceHolder1$CollectionDayLookup2$Button_SelectAddress"]
        del args["ctl00$ContentPlaceHolder1$CollectionDayLookup2$Button_PostCodeSearch"]
        args["ctl00$ContentPlaceHolder1$CollectionDayLookup2$Button_SelectAddress"] = "Continue+>"

        r = await http.post(_API_URL, data=args, check=False)
        if r.status_code != 200:
            raise InputError(
                f"Could not get correct data for postcode {postcode}; check {_API_URL} to validate the address."
            )

        page = soup(r.text)
        bin_tables = page.find_all("table")
        if not bin_tables:
            raise AddressNotFound(
                f"Could not get valid data for UPRN {uprn} and postcode {postcode}."
            )

        collections = []
        for bin_table in bin_tables:
            bin_text = bin_table.find("td", id=re.compile("CollectionDayLookup2_td_"))
            if not bin_text:
                continue

            bin_type_node = bin_text.find("b")
            if not bin_type_node:
                continue
            bin_type = bin_type_node.text.strip()

            date_node = bin_text.find(
                "span", id=re.compile(r"CollectionDayLookup2_Label_\w*_Date")
            )
            if not date_node or (
                " " not in date_node.text.strip()
                and date_node.text.strip().lower() != "today"
            ):
                continue

            date_text = date_node.text.strip()
            try:
                if date_text.lower() == "today":
                    collection_date = datetime.now().date()
                else:
                    collection_date = datetime.strptime(
                        date_text.split(" ")[1], "%d/%m/%Y"
                    ).date()
            except ValueError:
                continue

            collections.append(Collection(collection_date, bin_type))

        return collections


SCRAPER = Ashford()
