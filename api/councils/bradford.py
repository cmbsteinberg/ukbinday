"""Bradford: sets the UPRN cookie and reads collection dates from its HTML endpoint."""

from __future__ import annotations

from datetime import datetime

from api.councils._base import Address, Collection, Http, Meta, Scraper, soup, text_of

_API_URL = "https://onlineforms.bradford.gov.uk/ufs/"
_COOKIE_DOMAIN = "onlineforms.bradford.gov.uk"


class Bradford(Scraper):
    meta = Meta(
        title="Bradford Metropolitan District Council",
        url="https://bradford.gov.uk",
        lads=("E08000032",),
        cases={
            "Ilkley": {"uprn": "100051250665"},
            "Bradford": {"uprn": "100051239296"},
            "Baildon": {"uprn": "10002329242"},
        },
    )
    requires = frozenset({"uprn"})
    verify_tls = False

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        uprn = address.need("uprn")
        http.cookies.set("COLLECTIONDATES", uprn, domain=_COOKIE_DOMAIN)
        response = await http.get(f"{_API_URL}/collectiondates.eb")

        collections = []
        for region in soup(response.text).find_all("table", {"role": "region"}):
            display_classes = [
                class_name
                for class_name in region.get("class", [])
                if class_name.endswith("-Override-Panel")
            ]
            if not display_classes:
                continue

            headings = region.find_all(
                "td",
                {"class": display_classes[0].replace("Panel", "Header")},
            )
            bin_type = "UNKNOWN"
            heading_text = text_of(headings[0])
            if "General" in heading_text:
                bin_type = "REFUSE"
            elif "Recycling" in heading_text:
                bin_type = "RECYCLING"
            elif "Garden" in heading_text:
                bin_type = "GARDEN"

            for entry in region.find_all("div", {"type": "text"}):
                try:
                    day = datetime.strptime(text_of(entry), "%a %b %d %Y").date()
                except ValueError:
                    continue
                collections.append(Collection(day, bin_type))

        return collections


SCRAPER = Bradford()
