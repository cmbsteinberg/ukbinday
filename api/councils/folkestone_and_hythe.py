"""Folkestone & Hythe: prime the property page, then fetch collection cards via its AJAX endpoint."""

from __future__ import annotations

from datetime import datetime

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

_BASE = "https://service.folkestone-hythe.gov.uk/webapp/myarea"


class FolkestoneAndHythe(Scraper):
    meta = Meta(
        title="Folkestone and Hythe District Councol",
        url="https://www.folkestone-hythe.gov.uk/",
        lads=("E07000112",),
        cases={
            "Folkestone_Test": {"uprn": "50032102"},
            "Hythe_Test": {"uprn": "50019287"},
        },
    )
    requires = frozenset({"uprn"})
    transport = Transport.CURL_CFFI

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        uprn = address.need("uprn")
        index_url = f"{_BASE}/index.php?uprn={uprn}"

        await http.get(index_url)
        r = await http.get(
            f"{_BASE}/api_collections.php?uprn={uprn}",
            headers={"X-Requested-With": "fetch", "Referer": index_url},
        )

        collections = []
        for card in soup(r.text).select("article.service-card"):
            title = card.select_one("h3.service-title")
            when = card.select_one("p.service-next time[datetime]")
            if title is None or when is None or not when.get("datetime"):
                continue
            collections.append(
                Collection(
                    date=datetime.fromisoformat(when["datetime"]).date(),
                    type=title.get_text(strip=True),
                )
            )

        if not collections:
            raise UpstreamError(f"No collections found for UPRN {uprn}")

        return collections


SCRAPER = FolkestoneAndHythe()
