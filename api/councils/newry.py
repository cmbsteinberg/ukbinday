"""Newry, Mourne and Down: postcode search selects a collection-zone PDF calendar."""

from __future__ import annotations

import asyncio
import calendar
import io
import re
from datetime import date
from typing import Any
from urllib.parse import urljoin

from api.councils._base import (
    Address,
    AddressNotFound,
    Collection,
    Http,
    InputError,
    Meta,
    Scraper,
    UpstreamError,
    match_address,
    soup,
    weekday_number,
)

_URL = "https://www.newrymournedown.org/weekly-bin-collection-and-calendar"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
}
_BLUE = (0.098, 0.4627, 0.8235)
_BLACK = (0.0, 0.0, 0.0)
_BROWN = (0.4745, 0.3333, 0.2824)
_KIND_TYPE = {"blue": "Blue Bin", "black": "Black Bin", "brown": "Brown Bin"}


def _close(a: object, b: tuple[float, float, float]) -> bool:
    return (
        isinstance(a, (tuple, list))
        and len(a) == len(b)
        and all(isinstance(x, (int, float)) and abs(x - y) < 0.01 for x, y in zip(a, b, strict=False))
    )


def _is_red(col: object) -> bool:
    return (
        isinstance(col, (tuple, list))
        and len(col) == 3
        and isinstance(col[0], (int, float))
        and isinstance(col[1], (int, float))
        and isinstance(col[2], (int, float))
        and col[0] > 0.8
        and col[1] < 0.3
        and col[2] < 0.3
    )


def _parse_pdf(content: bytes, weekday: int) -> list[Collection]:
    import pdfplumber

    with pdfplumber.open(io.BytesIO(content)) as pdf:
        page = pdf.pages[0]
        title = "".join(c["text"] for c in page.chars)
        # Title text is rendered with doubled glyphs ("22002266--22002277").
        match = re.search(r"(20\d\d)-(20\d\d)", re.sub(r"(.)\1", r"\1", title))
        if not match or int(match.group(2)) != int(match.group(1)) + 1:
            raise ValueError("Could not read calendar year range from PDF title")
        start_year = int(match.group(1))

        boxes: list[tuple[int, float, str, Any]] = []
        for rect in page.rects:
            if not rect.get("fill"):
                continue
            colour = rect["non_stroking_color"]
            if _close(colour, _BLUE):
                kind = "blue"
            elif _close(colour, _BLACK):
                kind = "black"
            elif _close(colour, _BROWN):
                kind = "brown"
            else:
                continue
            if not (120 < rect["top"] < 450 and rect["height"] < 20):
                continue
            boxes.append((round(rect["top"]), rect["x0"], kind, rect))

        # Cell borders are separate stroked curves, one per date cell.
        borders = [
            (curve["x0"], curve["top"], curve["stroking_color"])
            for curve in page.curves
            if curve.get("stroke") and curve["width"] > 40 and 120 < curve["top"] < 450
        ]

    def border_of(rect: Any) -> object:
        for border_x, border_y, colour in borders:
            if abs(border_x - rect["x0"]) < 4 and abs(border_y - rect["top"]) < 4:
                return colour
        return None

    rows: dict[int, list[tuple[float, str, Any]]] = {}
    for top, x0, kind, rect in boxes:
        # Merge rows whose tops differ by sub-point rounding.
        key = next((row_top for row_top in rows if abs(row_top - top) <= 3), top)
        rows.setdefault(key, []).append((x0, kind, rect))
    ordered = [sorted(row, key=lambda item: item[0]) for _, row in sorted(rows.items())]
    if len(ordered) != 13:
        raise ValueError(f"Expected 13 month rows in PDF, found {len(ordered)}")

    rows_cells: list[list[tuple[list[str], object]]] = []
    rows_days: list[list[int]] = []
    rows_month: list[tuple[int, int]] = []
    for idx, row in enumerate(ordered):
        month = (3 + idx) % 12 + 1
        year = start_year + (3 + idx) // 12
        cells: list[tuple[list[str], object]] = []
        i = 0
        while i < len(row):
            _, kind, rect = row[i]
            if rect["width"] > 35:  # one wide box: a single bin
                cells.append(([_KIND_TYPE[kind]], border_of(rect)))
                i += 1
            elif i + 1 < len(row) and row[i + 1][2]["width"] < 35:
                # Two half-width boxes: both bins are collected.
                cells.append(
                    ([_KIND_TYPE[kind], _KIND_TYPE[row[i + 1][1]]], border_of(rect))
                )
                i += 2
            else:
                raise ValueError(
                    f"Unexpected box layout in {year}-{month:02d} row: "
                    f"{[(round(x), box_kind) for x, box_kind, _ in row]}"
                )

        rows_cells.append(cells)
        rows_days.append(
            [
                day
                for day in range(1, calendar.monthrange(year, month)[1] + 1)
                if date(year, month, day).weekday() == weekday
            ]
        )
        rows_month.append((year, month))

    # The leaflet stops part-way through the final April.
    if len(rows_cells[-1]) <= len(rows_days[-1]):
        rows_days[-1] = rows_days[-1][: len(rows_cells[-1])]

    # Some zones print a month's last date at the end of the next month's row.
    for idx in range(len(rows_cells) - 1):
        short = len(rows_days[idx]) - len(rows_cells[idx])
        if short > 0 and len(rows_cells[idx + 1]) - len(rows_days[idx + 1]) == short:
            rows_cells[idx].extend(rows_cells[idx + 1][-short:])
            del rows_cells[idx + 1][-short:]

    out: list[Collection] = []
    for cells, days, (year, month) in zip(rows_cells, rows_days, rows_month, strict=False):
        if len(days) != len(cells):
            raise ValueError(
                f"{year}-{month:02d}: {len(cells)} boxes but {len(days)} matching weekdays"
            )
        for day, (types, border) in zip(days, cells, strict=False):
            if _is_red(border):
                # Red border: a public-holiday alternative collection whose date
                # the PDF does not give.
                continue
            for bin_type in types:
                out.append(Collection(date(year, month, day), bin_type))
    return out


class Newry(Scraper):
    meta = Meta(
        title="Newry, Mourne and Down District Council",
        url=_URL,
        lads=("N09000010",),
        cases={
            "1 John Mitchel Street, Newry": {
                "postcode": "BT34 2AP",
                "house_number": "1",
                "street": "John Mitchel Street",
            },
            "9 Kildare Street, Newry": {
                "postcode": "BT34 1DQ",
                "house_number": "9",
                "street": "Kildare Street",
            },
            "44 Glenmore Road, Belleek": {
                "postcode": "BT35 7PU",
                "house_number": "44",
                "street": "Glenmore Road",
            },
        },
    )
    requires = frozenset({"postcode"})
    headers = _HEADERS

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        postcode = re.sub(r"\s+", "", address.need("postcode").strip().upper())
        if len(postcode) < 5:
            raise InputError("Invalid postcode")

        response = await http.post(
            _URL,
            data={
                "PostcodeBT": postcode[:-3],
                "PostcodeEND": postcode[-3:],
                "postback": "1",
                "submit_btn": "SEARCH",
            },
            timeout=30,
        )

        results: list[tuple[str, str]] = []
        for item in soup(response.text).select("div.list_downloads_sml li"):
            link = item.find("a", href=True)
            if link is None:
                continue
            label = re.sub(r"\s+", " ", item.get_text(" ", strip=True))
            label = label.replace("View Schedule", "").replace("\xa0", " ").strip()
            href = link.get("href")
            if isinstance(href, str):
                results.append((label.upper(), href))

        if not results:
            raise AddressNotFound(f"No addresses found for postcode {address.postcode}")

        if address.first_line:
            selected = match_address(address, results, text=lambda item: item[0])
            href = selected[1]
        else:
            hrefs = {link for _, link in results}
            if len(hrefs) != 1:
                raise InputError("Postcode spans several collection zones; supply an address")
            href = results[0][1]

        match = re.search(r"/([A-Z]{3})-[^/]+\.pdf", href, re.IGNORECASE)
        if not match:
            raise UpstreamError(f"Unrecognised schedule link {href!r}")
        try:
            weekday = weekday_number(match.group(1))
        except ValueError as exc:
            raise UpstreamError(f"Unrecognised schedule link {href!r}") from exc

        pdf = await http.get(urljoin(_URL, href), timeout=60)
        try:
            entries = await asyncio.to_thread(_parse_pdf, pdf.content, weekday)
        except ValueError as exc:
            raise UpstreamError(f"Could not parse Newry collection calendar: {exc}") from exc

        upcoming = [collection for collection in entries if collection.date >= date.today()]
        if not upcoming:
            raise UpstreamError("No upcoming collections in schedule PDF")
        return upcoming


SCRAPER = Newry()
