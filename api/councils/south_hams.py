"""South Hams: retrieve the next collection dates for a UPRN from its collections service."""

from __future__ import annotations

from datetime import datetime

from api.councils._base import (
    Address,
    Blocker,
    Collection,
    Http,
    Meta,
    Scraper,
    UpstreamError,
    soup,
)

_PAGE = "https://waste.southhams.gov.uk/mycollections"
_DETAILS = "https://waste.southhams.gov.uk/mycollections/getcollectiondetails"
_HEADERS = {
    "Content-Type": "application/x-www-form-urlencoded",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36",
    "Referer": _PAGE,
    "X-Requested-With": "XMLHttpRequest",
}


class SouthHams(Scraper):
    meta = Meta(
        title="South Hams",
        url="https://www.southhams.gov.uk",
        lads=("E07000044",),
        cases={},
    )
    requires = frozenset({"uprn"})
    blocker = Blocker.BOT_PROTECTION  # its site blocks Vercel's IPs (scripts/vercel_probe.py)

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        await http.get(_PAGE, check=False)
        fcc_session_token = http.cookies.get("fcc_session_cookie")
        if fcc_session_token is None:
            raise UpstreamError(
                f"Could not obtain session token from {_PAGE}. "
                "The service may be temporarily unavailable."
            )

        response = await http.post(
            _DETAILS,
            data={
                "fcc_session_token": fcc_session_token,
                "uprn": address.need("uprn"),
            },
            headers=_HEADERS,
            check=False,
        )

        collections: list[Collection] = []
        for tile in response.json()["binCollections"]["tile"]:
            page = soup(tile[0])
            for item in page.find_all("div", class_="collectionDiv"):
                # Plain .text: text_of's " " separator would split "date." across tags.
                h3 = item.find("h3")
                det = item.find("div", class_="detWrap")
                service_name = h3.text.strip() if h3 else ""
                details = det.text.strip() if det else ""
                next_collection = details.split("Your next scheduled collection is ")[1].split(".")[0]

                if next_collection.startswith("today"):
                    next_collection = next_collection.split("today, ")[1]
                elif next_collection.startswith("tomorrow"):
                    next_collection = next_collection.split("tomorrow, ")[1]

                collections.append(
                    Collection(
                        datetime.strptime(next_collection, "%A, %d %B %Y").date(),
                        service_name,
                    )
                )

        return collections


SCRAPER = SouthHams()
