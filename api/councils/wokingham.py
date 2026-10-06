"""Wokingham: search by postcode, select a property, then read its bin collection dates."""

from __future__ import annotations

from datetime import date, datetime

from api.councils._base import (
    Address,
    Collection,
    Http,
    Meta,
    Scraper,
    UpstreamError,
    match_address,
    soup,
    text_of,
)

_API_URL = (
    "https://www.wokingham.gov.uk/rubbish-and-recycling/waste-collection/"
    "find-your-bin-collection-day"
)
_CHRISTMAS_URL = (
    "https://www.wokingham.gov.uk/rubbish-and-recycling/christmas-bin-day-changes"
)
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:109.0) Gecko/20100101 Firefox/117.0",
    "Content-Type": "application/x-www-form-urlencoded",
    "Host": "www.wokingham.gov.uk",
    "Origin": "https://www.wokingham.gov.uk",
    "Referer": _API_URL,
}


def _form_id(markup: str) -> str:
    field = soup(markup).find("input", {"name": "form_build_id"})
    if field is None or not field.get("value"):
        raise UpstreamError("Wokingham's bin collection form has no build ID")
    return str(field["value"])


def _revised_schedules(markup: str) -> dict[date, date]:
    schedules: dict[date, date] = {}
    for row in soup(markup).find_all("tr"):
        cells = row.find_all("td")
        if len(cells) < 2:
            continue
        revised_text = cells[1].get_text().split(" (")[0]
        if revised_text == "Normal":
            continue
        try:
            original = datetime.strptime(
                cells[0].get_text(), "%A %d %B %Y"
            ).date()
            revised = datetime.strptime(revised_text, "%A %d %B %Y").date()
        except ValueError:
            continue
        schedules[original] = revised
    return schedules


class Wokingham(Scraper):
    meta = Meta(
        title="Wokingham Borough Council",
        url=_API_URL,
        lads=("E06000041",),
        cases={
            "Test_001": {"postcode": "RG40 1GE", "property": "10032935729"},
            "Test_002": {"postcode": "RG41 3BP", "property": "14007633"},
            "Test_004": {
                "postcode": "RG40 2LW",
                "house_number": "16",
                "street": "Davy Close",
            },
        },
    )
    requires = frozenset({"postcode"})

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        revised_schedules: dict[date, date] = {}
        try:
            holiday_response = await http.get(_CHRISTMAS_URL, timeout=10, check=False)
            if holiday_response.ok:
                revised_schedules = _revised_schedules(holiday_response.text)
        except UpstreamError:
            pass  # optional Christmas revisions page; the regular schedule stands without it

        response = await http.get(_API_URL)
        form_id = _form_id(response.text)
        postcode = address.need("postcode").upper().strip().replace(" ", "")

        response = await http.post(
            _API_URL,
            headers=_HEADERS,
            data={
                "postcode_search": postcode,
                "op": "Find Address",
                "form_build_id": form_id,
                "form_id": "waste_collection_api_form",
            },
        )
        form_id = _form_id(response.text)

        property_id = address.get("property")
        if property_id is None:
            options = soup(response.text).select(
                "div.form-item__dropdown option"
            )
            selected = match_address(
                address,
                options,
                text=text_of,
                uprn=lambda option: option.get("value"),
            )
            property_id = str(selected["value"])

        response = await http.post(
            _API_URL,
            headers=_HEADERS,
            data={
                "postcode_search": postcode,
                "address_options": property_id,
                "op": "Show collection dates",
                "form_build_id": form_id,
                "form_id": "waste_collection_api_form",
            },
        )

        collections: list[Collection] = []
        for card in soup(response.text).find_all("div", {"class": "card--waste"}):
            heading = card.find("h3")
            span = card.find("span")
            try:
                bin_type = text_of(heading).split("(")[0].strip()
                day_text = text_of(span).split()[-1]
                collection_date = datetime.strptime(day_text, "%d/%m/%Y").date()
            except (IndexError, ValueError):
                continue

            collection_date = revised_schedules.get(collection_date, collection_date)
            collections.append(Collection(collection_date, bin_type))

        return collections


SCRAPER = Wokingham()
