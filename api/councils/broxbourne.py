"""Broxbourne: fetch a CSRF token, then submit the postcode and UPRN to its bin collection form."""

from __future__ import annotations

from api.councils._base import (
    Address,
    Collection,
    Http,
    Meta,
    Scraper,
    UpstreamError,
    parse_date,
    soup,
)

_GET_SESSION_URL = "https://www.broxbourne.gov.uk/bin-collection-date"
_COLLECTION_URL = "https://www.broxbourne.gov.uk/xfp/form/205"
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
)


class Broxbourne(Scraper):
    meta = Meta(
        title="Borough of Broxbourne Council",
        url="https://www.broxbourne.gov.uk",
        lads=("E07000095",),
        cases={
            "Old School Cottage (Domestic Waste Only)": {
                "uprn": "148040092",
                "postcode": "EN10 7PX",
            },
            "11 Park Road (All Services)": {
                "uprn": "148028240",
                "postcode": "EN11 8PU",
            },
            "11 Pulham Avenue (All Services)": {
                "uprn": "148024643",
                "postcode": "EN10 7TA",
            },
        },
    )
    requires = frozenset({"uprn", "postcode"})
    headers = {"User-Agent": _USER_AGENT}

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        token_response = await http.get(_GET_SESSION_URL)
        token_input = soup(token_response.text).find("input", attrs={"name": "__token"})
        token = token_input.get("value") if token_input is not None else None
        if not token:
            raise UpstreamError("Could not parse CSRF token from Broxbourne's bin collection page")

        collection_response = await http.post(
            _COLLECTION_URL,
            data={
                "__token": token,
                "page": "490",
                "locale": "en_GB",
                "qacf7e570cf99fae4cb3a2e14d5a75fd0d6561058_0_0": address.need("postcode"),
                "qacf7e570cf99fae4cb3a2e14d5a75fd0d6561058_1_0": address.need("uprn"),
                "next": "Next",
            },
        )

        rows = soup(collection_response.text).find_all("tr")
        collections: list[Collection] = []
        for row in rows[1:]:  # Ignore the table header row.
            cells = row.find_all("td")
            try:
                waste_type = cells[1].get_text().rstrip()
                date_text = cells[0].get_text().split(" ")[0].replace("\xa0", " ")
                collection_date = parse_date(date_text)
            except (IndexError, ValueError):
                continue
            collections.append(Collection(collection_date, waste_type))

        return collections


SCRAPER = Broxbourne()
