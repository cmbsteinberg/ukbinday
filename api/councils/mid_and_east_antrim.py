"""Mid and East Antrim: SOAP lookup by UPRN, with bin dates read from its calendar."""

from __future__ import annotations

from datetime import datetime

from api.councils._base import (
    Address,
    Collection,
    Http,
    Meta,
    Scraper,
    find_tag,
    soup,
    text_of,
)

_API_URL = "https://collections-midandeastantrim.azurewebsites.net/WSCollExternal.asmx"

_PAYLOAD = """<?xml version="1.0" encoding="utf-8" ?>
<soap:Envelope xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
    xmlns:xsd="http://www.w3.org/2001/XMLSchema"
    xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
    <soap:Body>
        <getRoundCalendarForUPRN  xmlns="http://webaspx-collections.azurewebsites.net/">
            <council>MidAndEastAntrim</council>
            <UPRN>{uprn}</UPRN>
            <from>Chtml</from>
        </getRoundCalendarForUPRN >
    </soap:Body>
</soap:Envelope>
"""

_WASTE_TYPE_MAPPINGS = {
    "Ref date based on Round Name": "Refuse",
    "Grn date based on Round Name": "Garden",
    "Rec date based on Round Name": "Recycling",
}


def _bin_type_translation(page: object) -> dict[str, str]:
    translations: dict[str, str] = {}
    for bold in page.find_all("b"):
        if not text_of(bold).startswith("Key:"):
            continue
        key_div = bold.parent
        if key_div is None:
            break
        for span in key_div.find_all("span"):
            svg = span.find("svg")
            title = svg.find("title") if svg else None
            bin_type = text_of(title)
            if bin_type:
                translations[bin_type.lower()] = bin_type
        break
    return translations


class MidAndEastAntrim(Scraper):
    meta = Meta(
        title="Mid and East Antrim",
        url="https://www.midandeastantrim.gov.uk",
        lads=("N09000008",),
        cases={
            "185438838": {"uprn": "185438838"},
            "185448385": {"uprn": "185448385"},
            "187262293": {"uprn": "187262293"},
        },
    )
    requires = frozenset({"uprn"})

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        r = await http.post(
            _API_URL,
            content=_PAYLOAD.format(uprn=address.need("uprn").strip()),
            headers={"Content-Type": "text/xml; charset=utf-8"},
        )
        response_text = (
            r.text.replace("&lt;", "<")
            .replace("&gt;", ">")
            .replace("&amp;", "&")
            .split("<getRoundCalendarForUPRNResult>")[-1]
            .split("</getRoundCalendarForUPRNResult>")[0]
        )
        page = soup(response_text)
        translations = _bin_type_translation(page)

        calendar = find_tag(page, "div", {"id": "NewCalendar"}, what="Mid and East Antrim response has no calendar")

        collections: list[Collection] = []
        for table in calendar.find_all("table"):
            month_year = text_of(table.find("th"))
            day = 0
            for row in table.find_all("tr"):
                for cell in row.find_all("td"):
                    cell_text = text_of(cell)
                    if cell_text.isdigit():
                        day = int(cell_text)
                        continue

                    for svg in cell.find_all("svg"):
                        title = svg.find("title")
                        bin_type_raw = text_of(title)
                        if not bin_type_raw:
                            continue

                        try:
                            collection_date = datetime.strptime(
                                f"{day} {month_year}", "%d %B %Y"
                            ).date()
                        except ValueError:
                            continue

                        display_name = (
                            translations.get(bin_type_raw.lower())
                            or _WASTE_TYPE_MAPPINGS.get(bin_type_raw)
                            or bin_type_raw
                        )
                        collections.append(Collection(collection_date, display_name))

        return collections


SCRAPER = MidAndEastAntrim()
