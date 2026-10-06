"""East Lothian: search the schedule by postcode, resolve a UPRN, then fetch its iCalendar feed."""

from __future__ import annotations

from api.councils._base import (
    Address,
    AddressNotFound,
    Collection,
    Http,
    InputError,
    Meta,
    Scraper,
    Transport,
    find_tag,
    match_address,
    parse_ics,
    soup,
    text_of,
)

_BASE_URL = "https://www.eastlothian.gov.uk"
_SCHEDULE_URL = f"{_BASE_URL}/waste-collection-schedule"


def _parse_ics(ics_data: str) -> list[Collection]:
    collections: list[Collection] = []
    for event in parse_ics(ics_data):
        summary = event.summary.strip()
        if "download" in summary.lower() or "calendar" in summary.lower():
            continue

        type_str = summary.split(" for ", 1)[1] if " for " in summary else summary
        type_str = type_str.strip()
        if " and " in type_str.lower():
            for part in type_str.split(" and "):
                part = part.strip()
                collections.append(Collection(event.date, part))
        else:
            collections.append(Collection(event.date, type_str))
    return collections


class EastLothian(Scraper):
    meta = Meta(
        title="East Lothian",
        url="https://www.eastlothian.gov.uk/",
        lads=("S12000010",),
        cases={
            "EH21 8GU 4 Laing Loan, Wallyford": {
                "postcode": "EH21 8GU",
                "house_number": "4",
                "street": "Laing Loan",
            },
            "EH41 4LN Peterhouse, Morham": {
                "postcode": "EH41 4LN",
                "address": "Peterhouse, Morham, Haddington",
            },
            "1 Colliers Row Wallyford": {
                "postcode": "EH21 8GX",
                "house_number": "1",
                "street": "Colliers Row",
            },
        },
    )
    requires = frozenset({"postcode"})
    transport = Transport.CURL_CFFI

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        if address.uprn is None and address.first_line is None:
            raise InputError("East Lothian needs a UPRN or address")

        r = await http.get(_SCHEDULE_URL)
        form = find_tag(soup(r.text), "input", {"name": "form_build_id"}, what="Could not find form_build_id on East Lothian schedule page")
        form_build_id = form["value"]

        r = await http.post(
            _SCHEDULE_URL,
            data={
                "postcode": address.need("postcode"),
                "form_build_id": form_build_id,
                "form_id": "localgov_waste_collection_postcode_form",
                "op": "Find",
            },
            follow_redirects=True,
        )

        select = soup(r.text).find("select", {"name": "uprn"})
        if select is None:
            raise AddressNotFound(
                f"No address options found for postcode {address.postcode}"
            )

        options = [
            option
            for option in select.find_all("option")
            if option.get("value")
        ]
        selected = match_address(
            address,
            options,
            text=text_of,
            uprn=lambda option: option.get("value", ""),
        )
        uprn = str(selected["value"])

        r = await http.get(f"{_BASE_URL}/waste-collection-schedule/download/{uprn}")
        return _parse_ics(r.text)


SCRAPER = EastLothian()
