"""Chichester: submit a 12-digit UPRN to the bin-day form and parse its collection rows."""

from __future__ import annotations

import re
from datetime import datetime

from bs4 import Tag

from api.councils._base import (
    Address,
    Collection,
    Http,
    Meta,
    Scraper,
    Transport,
    UpstreamError,
    soup,
)

PAGE = "https://www.chichester.gov.uk/checkyourbinday"


class Chichester(Scraper):
    meta = Meta(
        title="Chichester District Council",
        url=PAGE,
        lads=("E07000225",),
        cases={
            "Test_001": {"uprn": "010002476348"},
            "Test_002": {"uprn": "100062612654"},
            "Test_003": {"uprn": "100061745708"},
        },
    )
    requires = frozenset({"uprn"})
    transport = Transport.CURL_CFFI

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        r = await http.get(PAGE)
        page = soup(r.text)

        form = page.find("form", attrs={"id": re.compile(r"WASTECOLLECTIONCALENDARV\d+_FORM")})
        if not isinstance(form, Tag):
            raise UpstreamError("Chichester bin-day form was not found")

        form_id = form.get("id")
        form_url = form.get("action")
        if not isinstance(form_id, str) or not isinstance(form_url, str):
            raise UpstreamError("Chichester bin-day form is missing its ID or action")

        form_id = form_id.split("_")[0]
        r = await http.post(
            form_url,
            data={
                f"{form_id}_FORMACTION_NEXT": "Submit",
                f"{form_id}_CALENDAR_UPRN": address.need("uprn").zfill(12),
            },
        )

        page = soup(r.text)
        collections = []
        for bin_div in page.find_all("div", class_=re.compile(r"binType-")):
            bin_type = bin_div.text.strip().title()
            date_div = bin_div.find_next_sibling("div")
            if not date_div:
                continue

            day = datetime.strptime(date_div.text.strip(), "%A %d %B %Y").date()
            collections.append(Collection(day, bin_type))

        return collections


SCRAPER = Chichester()
