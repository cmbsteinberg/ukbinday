"""Newham: looks up a UPRN and reads upcoming collections from its bin details page."""

from __future__ import annotations

from dateutil import parser as dateparser

from api.councils._base import Address, Collection, Http, Meta, Scraper, soup

_BASE = "https://bincollection.newham.gov.uk/Details/Index"


class Newham(Scraper):
    meta = Meta(
        title="London Borough of Newham",
        url="https://www.newham.gov.uk",
        lads=("E09000025",),
        cases={
            "Test_001": {"uprn": "46029461"},
            "Test_002": {"uprn": "46250697"},
            "Test_003": {"uprn": "46012509"},
        },
    )
    requires = frozenset({"uprn"})
    transport = __import__("api.councils._base", fromlist=["Transport"]).Transport.CURL_CFFI
    verify_tls = False

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        uprn = address.need("uprn").zfill(12)
        r = await http.get(f"{_BASE}/{uprn}")

        page = soup(r.text)
        entries: list[Collection] = []

        sections = page.find_all("div", {"class": "card h-100"})
        sections_recycling = page.find_all(
            "div", {"class": "card h-100 card-recycling"}
        )
        if len(sections_recycling) > 0:
            sections.append(sections_recycling[0])

        for item in sections:
            header = item.find("div", {"class": "card-header"})
            bin_type_element = header.find_next("b") if header else None
            if bin_type_element is None:
                continue
            bin_type = bin_type_element.text
            if bin_type not in ["Domestic", "Recycling"]:
                continue

            card_text = item.find("p", {"class": "card-text"})
            mark = card_text.find("mark") if card_text else None
            date_string = (
                mark.next_sibling.strip() if mark and mark.next_sibling else ""
            ).replace("\xa0", " ").strip()
            if not date_string:
                continue

            next_collection = dateparser.parse(date_string, dayfirst=True).date()
            entries.append(Collection(date=next_collection, type=bin_type))

        return entries


SCRAPER = Newham()
