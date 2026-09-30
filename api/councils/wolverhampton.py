"""Wolverhampton: fetches bin collections from the council page using postcode and UPRN."""

from __future__ import annotations

from datetime import datetime

from api.councils._base import Address, Collection, Http, Meta, Scraper, soup

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}


class Wolverhampton(Scraper):
    meta = Meta(
        title="Wolverhampton City Council",
        url="https://www.wolverhampton.gov.uk",
        lads=("E08000031",),
        cases={"Test Case": {"postcode": "WV1 1RD", "uprn": "10094887108"}},
    )
    requires = frozenset({"postcode", "uprn"})
    headers = _HEADERS

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        postcode = address.need("postcode").replace(" ", "").upper()
        uprn = address.need("uprn")
        url = f"https://www.wolverhampton.gov.uk/find-my-nearest/{postcode}/{uprn}"
        r = await http.get(url, timeout=30)

        page = soup(r.text)
        collections = []

        for container in page.find_all("div", class_="col-md-4"):
            waste_type_tag = container.find("h3")
            day_tag = container.find("h4")
            next_date_tag = day_tag.find_next_sibling("h4") if day_tag else None

            if waste_type_tag and day_tag and next_date_tag:
                waste_type_raw = waste_type_tag.text.strip()
                next_date_text = next_date_tag.text.replace("Next date: ", "").strip()

                try:
                    day = datetime.strptime(next_date_text, "%B %d, %Y").date()
                except ValueError:
                    continue

                collections.append(Collection(day, waste_type_raw))

        return collections


SCRAPER = Wolverhampton()
