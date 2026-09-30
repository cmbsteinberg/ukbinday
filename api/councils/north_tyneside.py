"""North Tyneside: fetches the waste-collection schedule directly by UPRN."""

from __future__ import annotations

from datetime import datetime

from api.councils._base import (
    Address,
    Collection,
    Http,
    Meta,
    Scraper,
    UpstreamError,
    soup,
)

SCHEDULE_URL = "https://www.northtyneside.gov.uk/waste-collection-schedule/view"


class NorthTyneside(Scraper):
    meta = Meta(
        title="North Tyneside",
        url="https://www.northtyneside.gov.uk/waste-collection-schedule",
        lads=("E08000022",),
        cases={},
    )
    requires = frozenset({"uprn"})
    verify_tls = False

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        uprn = address.need("uprn")
        r = await http.get(f"{SCHEDULE_URL}/{uprn}")
        schedule = soup(r.text).find("div", class_="waste-collection__schedule")
        if schedule is None:
            raise UpstreamError("No waste-collection schedule found. The page structure may have changed.")

        collections: list[Collection] = []
        for day in schedule.find_all("li", class_="waste-collection__day"):
            try:
                time_el = day.find("time")
                if time_el is None or not time_el.get("datetime"):
                    continue
                collection_date = datetime.strptime(time_el["datetime"], "%Y-%m-%d").date()

                type_span = day.find("span", class_="waste-collection__day--type")
                bin_type_text = type_span.find(string=True, recursive=False) if type_span else None
                if not bin_type_text:
                    continue
                bin_type = bin_type_text.strip()

                colour_span = day.find("span", class_="waste-collection__day--colour")
                if colour_span is None:
                    continue
                bin_colour = colour_span.get_text(strip=True)

                collections.append(Collection(collection_date, f"{bin_type} ({bin_colour})"))
            except (AttributeError, KeyError, TypeError, ValueError):
                continue

        return collections


SCRAPER = NorthTyneside()
