"""Comhairle nan Eilean Siar: searches area-based Lewis & Harris and Uist & Barra schedules."""

from __future__ import annotations

import re
from datetime import date
from re import Pattern

from bs4 import Tag

from api.councils._base import (
    Address,
    Collection,
    Http,
    InputError,
    Meta,
    Scraper,
    UpstreamError,
    parse_date,
    soup,
    text_of,
)

_BASE_URL = "https://www.cne-siar.gov.uk"

_LH_SCHEDULES = [
    (
        "Organic Food & Garden Waste / Mixed Recycling (Blue Bin)",
        "/bins-and-recycling/waste-recycling-collections-lewis-and-harris"
        "/organic-food-and-garden-waste-and-mixed-recycling-blue-bin",
        [
            "monday-collections",
            "tuesday-collections",
            "wednesday-collections",
            "thursday-collections",
            "friday-collections",
        ],
    ),
    (
        "Non-Recyclable Waste (Grey Bin)",
        "/bins-and-recycling/waste-recycling-collections-lewis-and-harris"
        "/non-recyclable-waste-grey-bin-purple-sticker",
        [
            "monday-collections",
            "tuesday-collections",
            "wednesday-collections",
            "thursday-collections",
            "friday-collections",
        ],
    ),
    (
        "Glass (Green Bin)",
        "/bins-and-recycling/waste-recycling-collections-lewis-and-harris"
        "/glass-green-bin-collections",
        ["thursday-collections", "friday-collections"],
    ),
]

_UB_RESIDUAL = (
    "Residual Waste (Black Bin)",
    "/bins-and-recycling/uist-and-barra"
    "/waste-recycling-collections-uist-and-barra/residual-bins-black-bins",
    ["tuesday-collections", "thursday-collections"],
)

_UB_RECYCLING = (
    None,
    "/bins-and-recycling/waste-recycling-collections-uist-and-barra"
    "/recycling-bins-blue-and-green",
    ["monday-collections", "tuesday-collections", "wednesday-collections"],
)

_LH_POSTCODES = {"HS1", "HS2", "HS3", "HS4", "HS5"}
_UB_POSTCODES = {"HS6", "HS7", "HS8", "HS9"}
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/138.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9",
}
_RECYCLING_PAPER = "Recycling - Paper/Card (Green Sticker)"
_RECYCLING_PLASTIC = "Recycling - Plastic/Tin (Blue Sticker)"


def _matches_area(search_term: str, area_name: str, locations_text: str) -> bool:
    """Match an area or location using word boundaries."""
    pattern: Pattern[str] = re.compile(
        r"(?<![a-z])" + re.escape(search_term) + r"(?![a-z])",
        re.IGNORECASE,
    )
    return bool(pattern.search(area_name) or pattern.search(locations_text))


def _parse_date_text(text: str) -> date | None:
    """Parse a date without a year, such as 'April 13th' or '1September'."""
    cleaned = re.sub(r"(\d+)(st|nd|rd|th)\b", r"\1", text.strip())
    cleaned = re.sub(r"(\d)([A-Za-z])", r"\1 \2", cleaned)
    try:
        return parse_date(cleaned)
    except ValueError:
        return None


def _parse_dates_from_text(text: str, month_name: str) -> list[date]:
    """Parse day numbers using the month supplied by a table column."""
    if not text or not month_name:
        return []

    dates: list[date] = []
    for day_text in re.findall(r"(\d+)(?:st|nd|rd|th)?", text):
        try:
            dates.append(parse_date(f"{day_text} {month_name}"))
        except ValueError:
            continue
    return dates


def _parse_lh_page(
    page_text: str,
    bin_type: str,
    search_term: str,
) -> list[Collection]:
    """Parse a Lewis & Harris accordion-style schedule page."""
    page = soup(page_text)
    collections: list[Collection] = []

    for pane in page.select("div.paragraph--type--localgov-accordion-pane"):
        button = pane.find("button")
        area_name = text_of(button)
        body = pane.find("div", class_="field--name-localgov-body-text")
        if not isinstance(body, Tag):
            continue

        full_text = body.get_text(" ", strip=True).lower()
        if not _matches_area(search_term, area_name.lower(), full_text):
            continue

        for item in body.find_all("li"):
            collection_date = _parse_date_text(item.get_text(strip=True))
            if collection_date is not None and collection_date > date.today():
                collections.append(Collection(collection_date, bin_type))

    return collections


def _parse_ub_accordion_panes(
    panes: list[Tag],
    bin_type: str | None,
    search_term: str,
    is_recycling: bool,
) -> list[Collection]:
    """Parse Uist & Barra accordion panes."""
    collections: list[Collection] = []

    for pane in panes:
        button = pane.find("button")
        area_text = text_of(button).lower()
        if not _matches_area(search_term, area_text, area_text):
            continue

        body = pane.find("div", class_="field--name-localgov-body-text")
        if not isinstance(body, Tag):
            continue

        current_type = bin_type
        for element in body.find_all(["h4", "ul"]):
            if element.name == "h4":
                label = element.get_text(strip=True).lower()
                if "paper" in label or "card" in label:
                    current_type = _RECYCLING_PAPER
                elif "plastic" in label or "tin" in label:
                    current_type = _RECYCLING_PLASTIC
                continue

            if not current_type:
                continue
            for item in element.find_all("li"):
                collection_date = _parse_date_text(item.get_text(strip=True))
                if collection_date is not None and collection_date > date.today():
                    collections.append(Collection(collection_date, current_type))

    return collections


def _parse_recycling_cell(cell: Tag, month_name: str) -> list[Collection]:
    """Parse Paper/Card and Plastic/Tin dates from a recycling table cell."""
    collections: list[Collection] = []

    for paragraph in cell.find_all("p"):
        strong = paragraph.find("strong")
        if not isinstance(strong, Tag):
            continue

        subtype = strong.get_text(strip=True).lower()
        if "paper" in subtype or "card" in subtype:
            bin_type = _RECYCLING_PAPER
        elif "plastic" in subtype or "tin" in subtype:
            bin_type = _RECYCLING_PLASTIC
        else:
            continue

        date_text = paragraph.get_text(" ", strip=True).replace(
            strong.get_text(strip=True), ""
        ).strip()
        for collection_date in _parse_dates_from_text(date_text, month_name):
            if collection_date > date.today():
                collections.append(Collection(collection_date, bin_type))

    return collections


def _parse_ub_page(
    page_text: str,
    bin_type: str | None,
    search_term: str,
    is_recycling: bool,
) -> list[Collection]:
    """Parse a Uist & Barra table or accordion-style schedule page."""
    page = soup(page_text)
    panes = page.select("div.paragraph--type--localgov-accordion-pane")
    if panes:
        return _parse_ub_accordion_panes(
            panes, bin_type, search_term, is_recycling
        )

    collections: list[Collection] = []
    for table in page.find_all("table"):
        headers: list[str] = []
        thead = table.find("thead")
        if isinstance(thead, Tag):
            headers = [th.get_text(strip=True) for th in thead.find_all("th")]
        month_headers = headers[1:] if len(headers) > 1 else []

        rows = table.find("tbody")
        if not isinstance(rows, Tag):
            continue

        for row in rows.find_all("tr"):
            cells = row.find_all("td")
            if not cells:
                continue

            area_text = cells[0].get_text(" ", strip=True).lower()
            if not _matches_area(search_term, area_text, area_text):
                continue

            for index, cell in enumerate(cells[1:]):
                month_name = month_headers[index] if index < len(month_headers) else ""
                if is_recycling:
                    collections.extend(_parse_recycling_cell(cell, month_name))
                    continue

                if not bin_type:
                    continue
                for collection_date in _parse_dates_from_text(
                    cell.get_text(" ", strip=True), month_name
                ):
                    if collection_date > date.today():
                        collections.append(Collection(collection_date, bin_type))

    return collections


def _search_terms(address: Address) -> list[str]:
    """Build the street and area search terms used by the council's schedules."""
    terms: list[str] = []
    if address.street:
        terms.append(address.street.strip())

    if address.label:
        skip = {
            (address.house_number or "").strip().lower(),
            (address.postcode or "").strip().lower(),
            (address.street or "").strip().lower(),
        }
        for part in address.label.split(","):
            part = part.strip()
            low = part.lower()
            if (
                not part
                or low in skip
                or re.fullmatch(r"hs\d+\s*\d\w\w", low)
                or re.fullmatch(r"\d+[a-z]?", low)
            ):
                continue
            terms.append(part)

    if not terms and address.house_number:
        terms.append(address.house_number)
    return terms


class NaHEileananSiar(Scraper):
    meta = Meta(
        title="Comhairle nan Eilean Siar",
        url="https://www.cne-siar.gov.uk",
        lads=("S12000013",),
        cases={},
    )
    requires = frozenset()
    headers = _HEADERS

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        terms = _search_terms(address)
        if not terms:
            raise InputError("A street or village name is required")

        postcode = (address.postcode or "").strip().upper()
        pc_district = postcode[:3].rstrip() if postcode else ""
        search_lh = not pc_district or pc_district in _LH_POSTCODES
        search_ub = not pc_district or pc_district in _UB_POSTCODES

        attempted_request = False
        successful_request = False

        for term in terms:
            search_term = term.strip().lower()
            collections: list[Collection] = []

            if search_lh:
                for bin_type, base_path, day_slugs in _LH_SCHEDULES:
                    for slug in day_slugs:
                        url = f"{_BASE_URL}{base_path}/{slug}"
                        attempted_request = True
                        try:
                            response = await http.get(url, timeout=30)
                        except UpstreamError:
                            continue
                        successful_request = True
                        collections.extend(
                            _parse_lh_page(response.text, bin_type, search_term)
                        )

            if search_ub:
                residual_label, residual_path, residual_slugs = _UB_RESIDUAL
                for slug in residual_slugs:
                    url = f"{_BASE_URL}{residual_path}/{slug}"
                    attempted_request = True
                    try:
                        response = await http.get(url, timeout=30)
                    except UpstreamError:
                        continue
                    successful_request = True
                    collections.extend(
                        _parse_ub_page(
                            response.text, residual_label, search_term, False
                        )
                    )

                _, recycling_path, recycling_slugs = _UB_RECYCLING
                for slug in recycling_slugs:
                    url = f"{_BASE_URL}{recycling_path}/{slug}"
                    attempted_request = True
                    try:
                        response = await http.get(url, timeout=30)
                    except UpstreamError:
                        continue
                    successful_request = True
                    collections.extend(
                        _parse_ub_page(response.text, None, search_term, True)
                    )

            if collections:
                return collections

        if attempted_request and not successful_request:
            raise UpstreamError("Comhairle nan Eilean Siar schedule pages could not be reached")

        raise InputError(
            f"No collection area found matching '{terms[0]}'. "
            "Try a village name (e.g. 'Back', 'Leverburgh', 'Castlebay') "
            "or street name (e.g. 'Goathill', 'Manor'). "
            "Check https://www.cne-siar.gov.uk/bins-and-recycling"
        )


SCRAPER = NaHEileananSiar()
