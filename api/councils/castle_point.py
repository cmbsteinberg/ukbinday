"""Castle Point: search the street register for a road ID, then read its collection calendar."""

from __future__ import annotations

import re
from datetime import date, datetime

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
    text_of,
)

_FETCH_SCHEDULE_URL = (
    "https://apps.castlepoint.gov.uk/cpapps/index.cfm"
    "?fa=myStreet.displayDetails&roadID="
)
_FIND_ROAD_URL = "https://apps.castlepoint.gov.uk/cpapps/index.cfm?fa=myStreet.search"

_NAME_MAP = {
    "normal": "Organic and Residual (Food/Garden/non-recyclable (black sack))",
    "pink": "Recycling (Food/Garden/Pink sack/Glass)",
}

_LEADING_HOUSE_NUMBER = re.compile(r"^\s*\d+[A-Za-z]?\s*(?:[-/,]\s*\d*[A-Za-z]?\s*)?")
_TRAILING_TOWN = re.compile(r"\s*\(([^)]*)\)\s*$")


def _normalise(value: str) -> str:
    """Upper-case and strip punctuation and extra spaces for comparison."""
    return re.sub(r"\s+", " ", re.sub(r"[^A-Z0-9 ]", " ", value.upper())).strip()


def _display(town: str, street_label: str) -> str:
    """Format a candidate as offered by the council."""
    return f"{street_label} ({town})" if town else street_label


def _match_tiers(town: str, street_label: str) -> list[str]:
    """Return the candidate names from most specific to least specific."""
    bare_label = street_label.split(" - ")[0]
    return [
        _normalise(_display(town, street_label)),
        _normalise(_display(town, bare_label)),
        _normalise(street_label),
        _normalise(bare_label),
    ]


def _search_terms(street: str) -> list[str]:
    """Simplify the supplied street name into terms accepted by the council search."""
    terms: list[str] = []

    def add(term: str) -> None:
        term = term.strip()
        if term and term not in terms:
            terms.append(term)

    add(street)
    without_number = _LEADING_HOUSE_NUMBER.sub("", street, count=1)
    add(without_number)
    without_town = _TRAILING_TOWN.sub("", without_number)
    add(without_town)
    add(without_town.split(" - ")[0])
    return terms


async def _search(http: Http, searchterm: str) -> list[tuple[str, str, str]]:
    """Return (town, street label, road ID) candidates for one search term."""
    response = await http.post(
        _FIND_ROAD_URL,
        data={"searchterm": searchterm},
        timeout=10,
    )
    page = soup(response.text)
    candidates: list[tuple[str, str, str]] = []

    for group in page.find_all("div", class_="flex-item-town"):
        town = text_of(group.find("h3"))
        for link in group.find_all("a", href=True):
            match = re.search(r"roadID=(\d+)", link["href"])
            if match:
                candidates.append((town, text_of(link), match.group(1)))

    return candidates


async def _get_road_id(http: Http, street: str) -> str:
    """Resolve a supplied street name to its unique council road ID."""
    terms = _search_terms(street)
    candidates: list[tuple[str, str, str]] = []

    for term in terms:
        candidates = await _search(http, term)
        if candidates:
            break

    matches: list[tuple[str, str, str]] = []
    for term in terms:
        wanted = _normalise(term)
        for tier in range(4):
            matches = [
                candidate
                for candidate in candidates
                if _match_tiers(candidate[0], candidate[1])[tier] == wanted
            ]
            if matches:
                break
        if matches:
            break

    if len(matches) == 1:
        return matches[0][2]
    if len(matches) > 1:
        raise AddressNotFound(
            f"Street {street!r} is ambiguous",
            [_display(town, label) for town, label, _ in matches],
        )

    raise AddressNotFound(
        f"No Castle Point street matches {street!r}",
        [_display(town, label) for town, label, _ in candidates],
    )


class CastlePoint(Scraper):
    meta = Meta(
        title="Castle Point Borough Council",
        url="https://www.castlepoint.gov.uk",
        lads=("E07000069",),
        cases={
            "Ash Road": {"street": "Ash Road"},
            "St Marys Road": {"street": "St Marys Road"},
            "High Street (Canvey Island)": {"street": "HIGH STREET (CANVEY ISLAND)"},
        },
    )
    requires = frozenset()

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        road_id = address.extra.get("roadID")
        if road_id is None:
            street = address.street
            if street is None:
                raise InputError("Either roadID or street is required to fetch waste collection schedule.")
            road_id = await _get_road_id(http, street)

        response = await http.get(f"{_FETCH_SCHEDULE_URL}{road_id}", timeout=10)
        page = soup(response.text)
        collections: list[Collection] = []
        now = datetime.now()

        for table in page.find_all("table", class_="calendar"):
            header = table.find("th")
            if not header:
                continue

            header_text = text_of(header).lower()
            month_match = re.search(
                r"(january|february|march|april|may|june|july|august|"
                r"september|october|november|december)",
                header_text,
            )
            if not month_match:
                continue

            month = datetime.strptime(month_match.group(1).capitalize(), "%B").month
            year_match = re.search(r"\b(\d{4})\b", header_text)
            if year_match:
                year = int(year_match.group(1))
            elif month < now.month - 6:
                year = now.year + 1
            else:
                year = now.year

            for element in table.select(".pink, .normal"):
                try:
                    day_match = re.search(r"\b(\d{1,2})\b", text_of(element))
                    if not day_match:
                        continue
                    day = int(day_match.group(1))
                    bin_type = (
                        _NAME_MAP["pink"]
                        if "pink" in element.get("class", [])
                        else _NAME_MAP["normal"]
                    )
                    collections.append(Collection(date(year, month, day), bin_type))
                except ValueError:
                    continue

        if not collections:
            raise UpstreamError(
                "Could not get collections for the specified road. The page structure may have changed."
            )
        return collections


SCRAPER = CastlePoint()
