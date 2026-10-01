"""Ards and North Down: fetches a UPRN-specific calendar HTML fragment from its API."""

from __future__ import annotations

from datetime import datetime

from bs4 import Tag

from api.councils._base import (
    Address,
    Collection,
    Http,
    Meta,
    Scraper,
    UpstreamError,
    soup,
)

_API_URL = "https://ardsandnorthdownbincalendar.azurewebsites.net/api/calendarhtml/{uprn}"


class ArdsAndNorthDown(Scraper):
    meta = Meta(
        title="Ards and North Down Borough Council",
        url="https://www.ardsandnorthdown.gov.uk/Recycle",
        lads=("N09000011",),
        cases={
            "185833845": {"uprn": "185833845"},
            "187340776": {"uprn": "185928695"},
            "185180798": {"uprn": "185180798"},
        },
    )
    requires = frozenset({"uprn"})

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        r = await http.get(_API_URL.format(uprn=address.need("uprn").strip()))
        html = r.json().get("calendarHTML", "")
        page = soup(html)

        bin_type_translation: dict[str, str] = {}
        key = next(
            (node for node in page.find_all(["b", "strong"]) if node.get_text().strip().startswith("Key:")),
            None,
        )
        if key is not None:
            for svg in key.find_all("svg"):
                title_tag = svg.find("title")
                if title_tag is None or not title_tag.get_text():
                    continue
                bin_name = title_tag.get_text().strip()
                fills = {
                    fill
                    for path in svg.find_all("path")
                    if isinstance((fill := path.get("fill")), str)
                    and fill.lower() not in ("#ffffff", "#000000")
                }
                for fill in fills:
                    bin_type_translation[fill] = bin_name

        calendar = page.find("div", {"id": "NewCalendar"})
        if not isinstance(calendar, Tag):
            raise UpstreamError("Ards and North Down calendar was missing")

        entries: list[Collection] = []
        for table in calendar.find_all("table"):
            heading = table.find("th")
            if heading is None:
                continue
            month_year = heading.get_text()
            day = 0

            for tr in table.find_all("tr"):
                for td in tr.find_all("td"):
                    cell_text = td.get_text().strip()
                    if cell_text.isdigit():
                        day = int(cell_text)
                        continue

                    svg = td.find("svg")
                    if svg:
                        day += 1
                        for path in svg.find_all("path"):
                            fill = path.get("fill")
                            if not isinstance(fill, str) or fill.lower() == "#ffffff":
                                continue
                            bin_name = bin_type_translation.get(fill)
                            if bin_name:
                                try:
                                    collection_date = datetime.strptime(
                                        f"{day} {month_year}", "%d %B %Y"
                                    ).date()
                                except ValueError:
                                    continue
                                entries.append(Collection(collection_date, bin_name))

        return entries


SCRAPER = ArdsAndNorthDown()
