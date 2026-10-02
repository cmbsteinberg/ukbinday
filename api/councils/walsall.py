"""Walsall: look up a UPRN and read dates from its linked bin schedules."""

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

_API_URL = "https://cag.walsall.gov.uk"


class Walsall(Scraper):
    meta = Meta(
        title="Walsall Council",
        url="https://www.walsall.gov.uk/",
        lads=("E08000030",),
        cases={
            "test001": {"uprn": "100071103746"},
            "test002": {"uprn": "100071105627"},
            "test003": {"uprn": "100071095946"},
        },
    )
    requires = frozenset({"uprn"})
    headers = {"user-agent": "Mozilla/5.0"}

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        uprn = address.need("uprn")
        r = await http.get(
            f"https://cag.walsall.gov.uk/BinCollections/GetBins?uprn={uprn}",
            check=False,
        )
        if r.status_code >= 400:
            # A block (403 from a cloud IP) must not read as "no collections".
            raise UpstreamError(f"HTTP {r.status_code} from {r.url}")
        schedule_links = soup(r.text).find_all("a", {"class": "select-bin"}, href=True)
        entries: list[Collection] = []
        for item in schedule_links:
            href = item["href"]
            if "roundname" not in href:
                continue
            bin_colour = href.split("=")[-1].split("%")[0].upper()
            r = await http.get(_API_URL + href, check=False)
            for td in soup(r.text).find_all("td"):
                try:
                    collection_date = datetime.strptime(
                        td.get_text().strip(), "%d/%m/%Y"
                    )
                except ValueError:
                    continue
                entries.append(Collection(collection_date.date(), bin_colour))
        return entries


SCRAPER = Walsall()
