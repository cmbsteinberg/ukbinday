"""Vale of White Horse: sets the UPRN cookie, then reads the current fortnight's bin dates."""

from __future__ import annotations

from datetime import datetime, timedelta

from api.councils._base import (
    Address,
    Collection,
    Http,
    Meta,
    Scraper,
    UpstreamError,
    soup,
)

_PAGE = "https://eform.whitehorsedc.gov.uk/ebase/BINZONE_DESKTOP.eb"
_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.7",
    "Cache-Control": "max-age=0",
    "Connection": "keep-alive",
    "Referer": "https://eform.whitehorsedc.gov.uk/ebase/BINZONE_DESKTOP.eb?SOVA_TAG=VALE&ebd=0&ebz=1_1704201201813",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-User": "?1",
    "Sec-GPC": "1",
    "Upgrade-Insecure-Requests": "1",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36",
}


class ValeOfWhiteHorse(Scraper):
    meta = Meta(
        title="Vale of White Horse",
        url=_PAGE,
        lads=("E07000180",),
        cases={},
    )
    requires = frozenset({"uprn"})
    headers = _HEADERS
    verify_tls = False

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        uprn = address.need("uprn")

        await http.get(
            f"{_PAGE}?SOVA_TAG=VALE&ebd=0&ebz=1_1780529431339",
            timeout=15,
        )
        http.cookies.set("SVBINZONE", f"VALE%3AUPRN%40{uprn}")
        response = await http.get(
            _PAGE,
            params={"SOVA_TAG": "VALE", "ebd": "0"},
            timeout=15,
        )

        page = soup(response.text)
        today = datetime.now().date()
        collections: list[Collection] = []

        for bin_node in page.find_all("div", {"class": "bintxt"}):
            try:
                bin_type_info = list(bin_node.stripped_strings)
                if "rubbish" in bin_type_info[0]:
                    bin_type = "Rubbish"
                elif "recycling" in bin_type_info[0]:
                    bin_type = "Recycling"
                else:
                    raise ValueError(f"No bin info found in {bin_type_info[0]}")

                bin_date_info = list(
                    bin_node.find_next("div", {"class": "binextra"}).stripped_strings
                )
                if "date" in bin_date_info[0].lower():
                    raw_date = bin_date_info[1]
                else:
                    raw_date = bin_date_info[0]

                bin_date = datetime.strptime(
                    f"{raw_date} {today.year}", "%A %d %B - %Y"
                ).date()
            except (AttributeError, IndexError, ValueError) as exc:
                raise UpstreamError(f"Error parsing Vale of White Horse bin data: {exc}") from exc

            while bin_date < today:
                bin_date += timedelta(days=14)

            collections.append(Collection(bin_date, bin_type))

        return collections


SCRAPER = ValeOfWhiteHorse()
