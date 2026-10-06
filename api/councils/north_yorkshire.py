"""North Yorkshire: POST the UPRN to the bin-calendar lookup, then fetch its AJAX collection data."""

from __future__ import annotations

from datetime import datetime

from api.councils._base import (
    Address,
    Collection,
    Http,
    InputError,
    Meta,
    Scraper,
    find_tag,
    soup,
)

_URL = "https://www.northyorks.gov.uk/bin-calendar/lookup"


class NorthYorkshire(Scraper):
    meta = Meta(
        title="North Yorkshire",
        url=_URL,
        lads=("E06000065",),
        cases={},
    )
    requires = frozenset({"uprn"})

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        response = await http.post(
            _URL,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={
                "selected_address": address.need("uprn"),
                "submit": "Continue",
                "form_id": "bin_calendar_lookup_form",
            },
        )
        response = await http.get(f"{response.url}/ajax")
        bin_data = response.json()

        html_data = None
        for item in bin_data:
            if isinstance(item, dict) and isinstance(item.get("data"), str) and "<div" in item["data"]:
                html_data = item["data"]
                break

        if not html_data:
            raise InputError("No HTML bin data found in API response")

        page = soup(html_data)
        table = find_tag(find_tag(find_tag(page, "div", {"id": "upcoming-collection"}), "table"), "tbody")
        collections = []

        for row in table.find_all("tr"):
            cols = row.find_all("td")
            bin_date = datetime.strptime(cols[0].text.strip(), "%d %B %Y").date()
            bin_types = [
                br.next_sibling.strip()
                for br in cols[2].find_all("i")
                if br.next_sibling
                and isinstance(br.next_sibling, str)
                and br.next_sibling.strip()
            ]
            for bin_type in bin_types:
                collections.append(Collection(bin_date, bin_type))

        return collections


SCRAPER = NorthYorkshire()
