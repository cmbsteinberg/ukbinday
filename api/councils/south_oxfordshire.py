"""South Oxfordshire: sets a UPRN cookie and reads collection dates from the bin page."""

from __future__ import annotations

from datetime import datetime, timedelta

from api.councils._base import Address, Collection, Http, Meta, Scraper, soup

_PAGE = "https://eform.southoxon.gov.uk/ebase/BINZONE_DESKTOP.eb"
_LANDING_URL = (
    "https://eform.southoxon.gov.uk/ebase/BINZONE_DESKTOP.eb"
    "?SOVA_TAG=SOUTH&ebd=0&ebz=1_1668467255368"
)
_PARAMS = {"SOVA_TAG": "SOUTH", "ebd": "0"}
_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.7",
    "Cache-Control": "max-age=0",
    "Connection": "keep-alive",
    "Referer": _LANDING_URL,
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-User": "?1",
    "Sec-GPC": "1",
    "Upgrade-Insecure-Requests": "1",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36",
}


def _contains_date(text: str, year: int) -> bool:
    try:
        datetime.strptime(f"{text} {year}", "%A %d %B - %Y")
    except ValueError:
        return False
    return True


class SouthOxfordshire(Scraper):
    meta = Meta(
        title="South Oxfordshire",
        url="https://www.southoxon.gov.uk/south-oxfordshire-district-council/recycling-rubbish-and-waste/when-is-your-collection-day/",
        lads=("E07000179",),
        cases={},
    )
    requires = frozenset({"uprn"})
    headers = _HEADERS
    verify_tls = False

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        uprn = address.need("uprn")

        await http.get(_LANDING_URL, timeout=15, check=False)
        http.cookies.set("SVBINZONE", f"SOUTH%3AUPRN%40{uprn}")
        response = await http.get(
            _PAGE,
            params=_PARAMS,
            headers=_HEADERS,
            timeout=15,
            check=False,
        )

        page = soup(response.text)
        today = datetime.now().date()
        collections: list[Collection] = []

        for bin_container in page.find_all("div", {"class": "binextra"}):
            bin_info = list(bin_container.stripped_strings)
            try:
                if _contains_date(bin_info[0], today.year):
                    raw_date = bin_info[0]
                    type_start = 1
                else:
                    raw_date = bin_info[1]
                    type_start = 2

                bin_date = datetime.strptime(
                    f"{raw_date} {today.year}", "%A %d %B - %Y"
                ).date()

                type_parts = []
                for part in bin_info[type_start:]:
                    if "don't" in part.lower() or part.startswith("Extra"):
                        break
                    type_parts.append(part)
                combined_type = " ".join(type_parts)
            except (IndexError, ValueError):
                continue

            while bin_date < today:
                bin_date += timedelta(days=14)

            for bin_type in combined_type.replace(" and ", ", ").split(","):
                bin_type = bin_type.strip().capitalize()
                if bin_type:
                    collections.append(Collection(bin_date, bin_type))

        return collections


SCRAPER = SouthOxfordshire()
