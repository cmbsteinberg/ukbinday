"""Broadland and South Norfolk: postcode address search or My Area payload, with a South Norfolk SOAP calendar when available."""

from __future__ import annotations

import ast
import calendar
import json
import re
from datetime import date
from html import unescape
from time import strptime
from urllib.parse import quote
from xml.etree import ElementTree as ET

from api.councils._base import (
    Address,
    AddressNotFound,
    Collection,
    Http,
    InputError,
    Meta,
    Scraper,
    Transport,
    UpstreamError,
    match_address,
    soup,
)

_TITLE = "Broadland District Council"
_URL = "https://area.southnorfolkandbroadland.gov.uk/"
_SNC_CALENDAR_HOST = "collections-southnorfolk.azurewebsites.net"
_SNC_SOAP_URL = f"https://{_SNC_CALENDAR_HOST}/WSCollExternal.asmx"
_SNC_SOAP_NS = "http://webaspx-collections.azurewebsites.net/"
_SNC_SOAP_ACTION = '"http://webaspx-collections.azurewebsites.net/getRoundCalendarForUPRN"'
_SNC_BIN_TYPE_PREFIXES = {
    "Ref": "Rubbish",
    "Rec": "Recycling",
    "Foo": "Food",
    "Grn": "Garden",
    "Gar": "Garden",
}
_DATE_PATTERN = re.compile(r"^([A-Z][a-z]+) (\d{1,2}) ([A-Z][a-z]+) (\d{4})$")


def _parse_date(date_text: str) -> date:
    match = _DATE_PATTERN.match(date_text)
    if match is None:
        raise ValueError(f"Unable to parse date {date_text}")
    return date(
        int(match.group(4)),
        strptime(match.group(3)[:3], "%b").tm_mon,
        int(match.group(2)),
    )


def _parse_snc_svg_title(title_text: str) -> list[str]:
    """Extract the waste types named by lines in an SVG calendar title."""
    bin_types: list[str] = []
    for line in title_text.strip().split("\n"):
        line = line.strip()
        for prefix, name in _SNC_BIN_TYPE_PREFIXES.items():
            if line.startswith(prefix) and name not in bin_types:
                bin_types.append(name)
                break
    return bin_types


def _payload(value: str) -> dict[str, object]:
    try:
        parsed = json.loads(value)
    except ValueError:
        try:
            parsed = ast.literal_eval(value)
        except (SyntaxError, ValueError) as exc:
            raise InputError("Invalid address_payload") from exc
    if not isinstance(parsed, dict):
        raise InputError("Invalid address_payload")
    return parsed


def _option_uprn(option: object) -> str:
    value = option.get("value", "") if hasattr(option, "get") else ""
    return value.split(";")[0]


class BroadlandAndSouthNorfolk(Scraper):
    meta = Meta(
        title=_TITLE,
        url=_URL,
        lads=("E07000144", "E07000149"),
        cases={
            "Broadland residential address": {
                "postcode": "NR7 8DN",
                "house_number": "29",
                "street": "Mallard Way",
            },
            "South Norfolk residential address": {
                "postcode": "NR14 8BX",
                "house_number": "1",
                "street": "Brindle Drive",
            },
        },
    )
    requires = frozenset()
    transport = Transport.CURL_CFFI

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        payload_value = address.get("address_payload")
        if payload_value is not None:
            r = await http.get(
                _URL,
                headers={"Cookie": f"MyArea.Data={quote(json.dumps(_payload(payload_value)))}"},
            )
            return await self._get_data(r.text, address, http)

        if address.postcode is None or (address.label is None and address.first_line is None):
            raise InputError("Either address_payload or postcode and address must be provided")

        r = await http.get(_URL + "FindAddress")
        page = soup(r.text)
        token = page.find("input", {"name": "__RequestVerificationToken"})
        if token is None or not token.get("value"):
            raise UpstreamError("Broadland and South Norfolk address form has no verification token")

        args = {
            "Postcode": address.postcode.replace(",", "").replace(" ", "").lower(),
            "__RequestVerificationToken": token["value"],
        }
        r = await http.post(_URL + "FindAddress", data=args)
        page = soup(r.text)
        select = page.find("select", {"id": "UprnAddress"})
        options = select.find_all("option") if select is not None else []
        if not options:
            raise AddressNotFound(f"No addresses for postcode {address.postcode}")

        token = page.find("input", {"name": "__RequestVerificationToken"})
        if token is None or not token.get("value"):
            raise UpstreamError("Broadland and South Norfolk address form has no verification token")
        args["__RequestVerificationToken"] = token["value"]

        selected = match_address(
            address,
            options,
            text=lambda option: option.get_text(strip=True),
            uprn=_option_uprn,
        )
        args["UprnAddress"] = selected.get("value", "")

        r = await http.post(_URL + "FindAddress/Submit", data=args)
        return await self._get_data(r.text, address, http)

    async def _get_data(self, markup: str, address: Address, http: Http) -> list[Collection]:
        page = soup(markup)
        heading = page.find("h3", string="Bins")
        if heading is None or heading.parent is None:
            raise UpstreamError("Broadland and South Norfolk page has no bins card")
        bins_card = heading.parent

        snc_link = bins_card.find(
            "a", href=lambda href: href is not None and _SNC_CALENDAR_HOST in href
        )
        if snc_link is not None:
            match = re.search(r"UPRN=(\d+)", snc_link.get("href", ""))
            if match:
                return await self._fetch_snc_soap_calendar(match.group(1), http)

        collections: list[Collection] = []
        for bin_category in bins_card.find_all("div", {"class": "card-text"}):
            children = tuple(bin_category.children)
            try:
                day = _parse_date(children[3].strip())
                bin_type = children[1].text.strip()
            except (AttributeError, IndexError, ValueError):
                continue
            collections.append(Collection(day, bin_type))
        return collections

    async def _fetch_snc_soap_calendar(self, uprn: str, http: Http) -> list[Collection]:
        soap_body = (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<soap:Envelope xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"'
            ' xmlns:xsd="http://www.w3.org/2001/XMLSchema"'
            ' xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">'
            "<soap:Body>"
            f'<getRoundCalendarForUPRN xmlns="{_SNC_SOAP_NS}">'
            "<council>SNO</council>"
            "<webServicePassword></webServicePassword>"
            "<username></username>"
            "<usernamePassword></usernamePassword>"
            f"<UPRN>{uprn}</UPRN>"
            "<from>Chtml</from>"
            "</getRoundCalendarForUPRN>"
            "</soap:Body>"
            "</soap:Envelope>"
        )
        r = await http.post(
            _SNC_SOAP_URL,
            headers={
                "Content-Type": "text/xml; charset=utf-8",
                "SOAPAction": _SNC_SOAP_ACTION,
            },
            content=soap_body.encode("utf-8"),
        )
        try:
            root = ET.fromstring(r.text)
        except ET.ParseError as exc:
            raise UpstreamError("South Norfolk calendar returned invalid XML") from exc

        namespace = f"{{{_SNC_SOAP_NS}}}"
        result_el = root.find(f".//{namespace}getRoundCalendarForUPRNResult")
        if result_el is None:
            raise UpstreamError("South Norfolk calendar response has no getRoundCalendarForUPRNResult")
        if not result_el.text:
            return []

        calendar_page = soup(unescape(result_el.text))
        collections: list[Collection] = []
        for table in calendar_page.find_all(
            "table", id=lambda value: value is not None and value.startswith("CalTab")
        ):
            heading = table.find("th", class_="thMidHC")
            if heading is None:
                continue
            try:
                month_name, year_text = heading.get_text(strip=True).split(" ")
                year = int(year_text)
                month = list(calendar.month_name).index(month_name)
                first_weekday, days_in_month = calendar.monthrange(year, month)
            except (ValueError, IndexError):
                continue

            for row_index, row in enumerate(table.find_all("tr")[2:]):
                for column_index, cell in enumerate(row.find_all("td")[1:]):
                    day = row_index * 7 + column_index - first_weekday + 1
                    if day < 1 or day > days_in_month:
                        continue
                    svg = cell.find("svg")
                    title = svg.find("title") if svg is not None else None
                    if title is None:
                        continue
                    try:
                        collection_day = date(year, month, day)
                    except ValueError:
                        continue
                    for bin_type in _parse_snc_svg_title(title.get_text()):
                        collections.append(Collection(collection_day, bin_type))
        return collections


SCRAPER = BroadlandAndSouthNorfolk()
