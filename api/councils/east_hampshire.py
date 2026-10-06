"""East Hampshire: look up bin calendars by UPRN or manual calendar numbers, then parse their PDFs."""

from __future__ import annotations

import asyncio
import re
from datetime import date
from io import BytesIO
from urllib.parse import urljoin

from bs4 import Tag
from pypdf import PdfReader
from pypdf._page import PageObject
from pypdf.generic import ContentStream

from api.councils._base import (
    Address,
    AddressNotFound,
    Collection,
    Http,
    InputError,
    Meta,
    Scraper,
    UpstreamError,
    soup,
)

_URL = "https://www.easthants.gov.uk"
_SCHEDULE_URL = f"{_URL}/bin-collections/find-your-bin-calendar"
_ADDRESS_URL = "https://maps.easthants.gov.uk/easthampshire.aspx"
_HEADERS = {"User-Agent": "waste-collection-schedule/easthants_gov_uk"}
_MONTHS = {
    "JAN": 1,
    "FEB": 2,
    "MAR": 3,
    "APR": 4,
    "MAY": 5,
    "JUN": 6,
    "JUL": 7,
    "AUG": 8,
    "SEP": 9,
    "OCT": 10,
    "NOV": 11,
    "DEC": 12,
}
_MONTH_RE = re.compile(r"^(" + "|".join(_MONTHS) + r")\s+(20\d{2})$")
_DATE_RE = re.compile(r"^(?:MON|TUE|WED|THU|FRI|SAT|SUN)\s+(\d{1,2})$")
_CALENDAR_LINK_RE = re.compile(r"^Calendar\s+(\d+)\b", re.IGNORECASE)
_GARDEN_CALENDAR_LINK_RE = re.compile(r"^G(\d+)\b", re.IGNORECASE)

_RUBBISH_COLOUR = (0.248, 0.646, 0.209)
_RECYCLING_COLOUR = (0.391, 0.389, 0.387)
_HARD_TO_REACH_RECYCLING_COLOUR = (0.438, 0.437, 0.434)
_GLASS_COLOUR = (0.0, 0.46, 0.748)
_GARDEN_COLOUR = (0.6, 0.71, 1.0, 0.3)
_SUSPENDED_COLOUR = (0.31, 0.98, 0.0, 0.0)
_COLOUR_TOLERANCE = 0.02

_TYPE_MAP = {
    "rubbish": ("Rubbish",),
    "recycling": ("Recycling",),
    "glass": ("Glass",),
    "garden": ("Garden waste",),
}


def _colour_matches(
    actual: tuple[float, ...] | None, expected: tuple[float, ...]
) -> bool:
    return bool(
        actual
        and len(actual) == len(expected)
        and all(
            abs(actual[index] - expected[index]) <= _COLOUR_TOLERANCE
            for index in range(len(expected))
        )
    )


def _calendar_links(html: str) -> tuple[dict[int, str], dict[int, str]]:
    page = soup(html)
    links: dict[int, str] = {}
    garden_links: dict[int, str] = {}

    for anchor in page.find_all("a", href=True):
        label = " ".join(anchor.stripped_strings)
        match = _CALENDAR_LINK_RE.match(label)
        if match:
            links[int(match.group(1))] = urljoin(_SCHEDULE_URL, str(anchor["href"]))
            continue

        garden_match = _GARDEN_CALENDAR_LINK_RE.match(label)
        if garden_match:
            garden_links[int(garden_match.group(1))] = urljoin(
                _SCHEDULE_URL, str(anchor["href"])
            )

    return links, garden_links


def _secure_calendar_url(href: str) -> str:
    url = urljoin(_ADDRESS_URL, href)
    if url.startswith("http://maps.easthants.gov.uk/"):
        return "https://" + url.removeprefix("http://")
    return url


def _uprn_calendar_urls(html: str, uprn: str) -> dict[str, str]:
    page = soup(html)
    panel = page.find(
        "div", attrs={"aria-label": re.compile("waste and recycling", re.IGNORECASE)}
    )
    if not isinstance(panel, Tag):
        raise AddressNotFound(f"No East Hampshire address was found for UPRN {uprn}.")

    urls: dict[str, str] = {}
    for heading in panel.find_all("h4"):
        section = heading.find_parent("div", class_="atPanelContent")
        if not isinstance(section, Tag):
            continue
        link = section.find("a", href=True)
        if not isinstance(link, Tag):
            continue

        title = heading.get_text(" ", strip=True).casefold()
        if "garden" in title:
            urls["garden"] = _secure_calendar_url(str(link["href"]))
        elif "bin calendar" in title:
            urls["bins"] = _secure_calendar_url(str(link["href"]))

    if "bins" not in urls:
        raise AddressNotFound(
            f"The council did not provide a bin calendar for UPRN {uprn}."
        )
    return urls


def _collection_rectangles(
    page: PageObject, reader: PdfReader
) -> list[tuple[float, float, float, float, str]]:
    """Return collection-type rectangles as (x0, y0, x1, y1, type_key)."""
    rectangles: list[tuple[float, float, float, float, str]] = []
    fill_colour: tuple[float, ...] | None = None
    colour_stack: list[tuple[float, ...] | None] = []

    content = ContentStream(page.get_contents(), reader)
    for operands, operator in content.operations:
        if operator == b"q":
            colour_stack.append(fill_colour)
        elif operator == b"Q":
            fill_colour = colour_stack.pop() if colour_stack else None
        elif operator in (b"rg", b"scn") and len(operands) >= 3:
            try:
                fill_colour = tuple(float(value) for value in operands[:3])
            except (TypeError, ValueError):
                fill_colour = None
        elif operator == b"k" and len(operands) >= 4:
            try:
                fill_colour = tuple(float(value) for value in operands[:4])
            except (TypeError, ValueError):
                fill_colour = None
        elif operator == b"g" and operands:
            try:
                grey = float(operands[0])
            except (TypeError, ValueError):
                fill_colour = None
            else:
                fill_colour = (grey, grey, grey)
        elif operator == b"re" and len(operands) == 4:
            if _colour_matches(fill_colour, _RUBBISH_COLOUR):
                type_key = "rubbish"
            elif _colour_matches(
                fill_colour, _RECYCLING_COLOUR
            ) or _colour_matches(fill_colour, _HARD_TO_REACH_RECYCLING_COLOUR):
                type_key = "recycling"
            elif _colour_matches(fill_colour, _GLASS_COLOUR):
                type_key = "glass"
            elif _colour_matches(fill_colour, _GARDEN_COLOUR):
                type_key = "garden"
            elif _colour_matches(fill_colour, _SUSPENDED_COLOUR):
                type_key = "suspended"
            else:
                continue

            try:
                x, y, width, height = (float(value) for value in operands)
            except (TypeError, ValueError):
                continue

            # Date cells are 53-71pt wide; ignore icon artwork and large legends.
            if not (10 <= abs(width) <= 75 and 10 <= abs(height) <= 16):
                continue

            rectangles.append(
                (
                    min(x, x + width),
                    min(y, y + height),
                    max(x, x + width),
                    max(y, y + height),
                    type_key,
                )
            )

    return rectangles


def _type_at_position(
    rectangles: list[tuple[float, float, float, float, str]],
    text_x: float,
    text_y: float,
) -> str | None:
    # Include the bank-holiday icon cell without reaching the next calendar column.
    for x0, y0, x1, y1, type_key in rectangles:
        if y0 - 1 <= text_y <= y1 + 1 and x1 >= text_x - 5 and x0 <= text_x + 70:
            return type_key
    return None


def _waste_types(type_key: str, separate_glass: bool) -> tuple[str, ...]:
    if type_key == "recycling" and not separate_glass:
        return (*_TYPE_MAP[type_key], "Glass")
    return _TYPE_MAP[type_key]


def _normalise_heading_year(
    printed_year: int, month: int, previous: tuple[int, int] | None
) -> int:
    """Correct an inconsistent printed year using the month sequence."""
    if previous is None:
        return printed_year

    previous_year, previous_month = previous
    expected_year = previous_year + int(month < previous_month)
    if printed_year != expected_year:
        # The printed year is wrong; the month sequence is authoritative.
        return expected_year
    return printed_year


def _parse_page(page: PageObject, reader: PdfReader) -> list[Collection]:
    rectangles = _collection_rectangles(page, reader)
    separate_glass = any(type_key == "glass" for *_, type_key in rectangles)
    fragments: list[tuple[str, float, float]] = []

    def collect_text(
        text: str,
        _cm: object,
        tm: object,
        _font: object,
        _font_size: float,
    ) -> None:
        cleaned = " ".join(text.split()).upper()
        if cleaned:
            fragments.append((cleaned, float(tm[4]), float(tm[5])))  # type: ignore[index]

    page.extract_text(visitor_text=collect_text)

    current_month_by_column: dict[float, tuple[int, int]] = {}
    collections: list[Collection] = []
    unmatched_dates: list[str] = []

    for text, text_x, text_y in fragments:
        column = round(text_x, 1)
        if month_match := _MONTH_RE.fullmatch(text):
            month = _MONTHS[month_match.group(1)]
            printed_year = int(month_match.group(2))
            current_month_by_column[column] = (
                _normalise_heading_year(
                    printed_year, month, current_month_by_column.get(column)
                ),
                month,
            )
            continue

        date_match = _DATE_RE.fullmatch(text)
        if not date_match or column not in current_month_by_column:
            continue

        year, month = current_month_by_column[column]
        collection_date = date(year, month, int(date_match.group(1)))
        type_key = _type_at_position(rectangles, text_x, text_y)
        if type_key is None:
            unmatched_dates.append(collection_date.isoformat())
            continue
        if type_key == "suspended":
            continue

        collections.extend(
            Collection(collection_date, waste_type)
            for waste_type in _waste_types(type_key, separate_glass)
        )

    if unmatched_dates:
        raise ValueError(
            "Could not determine collection types for PDF dates: "
            + ", ".join(unmatched_dates)
        )

    return collections


def _parse_pdf(content: bytes) -> list[Collection]:
    reader = PdfReader(BytesIO(content))
    collections: list[Collection] = []
    for page in reader.pages:
        collections.extend(_parse_page(page, reader))
    return collections


def _validate_calendar_number(argument: str, value: str) -> int:
    try:
        calendar_number = int(value)
    except ValueError as exc:
        raise InputError(f"{argument} must be a positive integer") from exc

    if calendar_number < 1:
        raise InputError(f"{argument} must be a positive integer")
    return calendar_number


def _validate_uprn(value: str) -> str:
    uprn = value.strip()
    if not uprn.isdigit():
        raise InputError("UPRN must contain only digits")
    return uprn


async def _fetch_calendar(http: Http, url: str, calendar_name: str) -> list[Collection]:
    response = await http.get(url, timeout=60)
    try:
        collections = await asyncio.to_thread(_parse_pdf, response.content)
    except ValueError as exc:
        raise UpstreamError(
            f"Could not parse East Hampshire calendar {calendar_name}: {exc}"
        ) from exc
    if not collections:
        raise UpstreamError(
            f"No collection dates found in East Hampshire calendar {calendar_name}. "
            "The PDF format may have changed."
        )
    return collections


class EastHampshire(Scraper):
    meta = Meta(
        title="East Hampshire District Council",
        url=_URL,
        lads=("E07000085",),
        cases={
            "UPRN lookup": {"uprn": "1710041123"},
            "Calendar 16 with garden waste G1": {
                "calendar_number": "16",
                "garden_calendar_number": "1",
            },
            "Calendar 1 without garden waste": {"calendar_number": "1"},
        },
    )
    requires = frozenset()
    headers = _HEADERS

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        uprn_value = address.uprn
        calendar_value = address.get("calendar_number")
        garden_calendar_value = address.get("garden_calendar_number")

        uprn = _validate_uprn(uprn_value) if uprn_value is not None else None
        calendar_number = (
            _validate_calendar_number("calendar_number", calendar_value)
            if calendar_value is not None
            else None
        )
        garden_calendar_number = (
            _validate_calendar_number("garden_calendar_number", garden_calendar_value)
            if garden_calendar_value is not None
            else None
        )

        if uprn is None and calendar_number is None:
            raise InputError("Provide a UPRN or a manual calendar number.")

        if uprn is not None:
            response = await http.get(
                _ADDRESS_URL,
                params={"action": "SetAddress", "UniqueId": uprn},
                timeout=30,
            )
            urls = _uprn_calendar_urls(response.text, uprn)
            collections = await _fetch_calendar(
                http, urls["bins"], f"for UPRN {uprn}"
            )
            if "garden" in urls:
                collections.extend(
                    await _fetch_calendar(
                        http, urls["garden"], f"garden for UPRN {uprn}"
                    )
                )
            return collections

        response = await http.get(_SCHEDULE_URL, timeout=30)
        links, garden_links = _calendar_links(response.text)
        if calendar_number not in links:
            suggestions = [str(number) for number in sorted(links)]
            raise AddressNotFound(
                f"East Hampshire has no calendar number {calendar_number}.",
                suggestions,
            )

        collections = await _fetch_calendar(
            http, links[calendar_number], str(calendar_number)
        )

        if garden_calendar_number is not None:
            if garden_calendar_number not in garden_links:
                suggestions = [str(number) for number in sorted(garden_links)]
                raise AddressNotFound(
                    f"East Hampshire has no garden calendar number "
                    f"{garden_calendar_number}.",
                    suggestions,
                )
            collections.extend(
                await _fetch_calendar(
                    http,
                    garden_links[garden_calendar_number],
                    f"G{garden_calendar_number}",
                )
            )

        return collections


SCRAPER = EastHampshire()
