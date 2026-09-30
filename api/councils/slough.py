"""Slough: search the bin directory by street, then follow each bin's collection-date link."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from api.councils._base import (
    Address,
    AddressNotFound,
    Collection,
    Http,
    InputError,
    Meta,
    Scraper,
    soup,
    text_of,
)

_TITLE = "Slough Borough Council"
_URL = "https://www.slough.gov.uk"
_DIRECTORY_SEARCH_URL = "https://www.slough.gov.uk/directory/search"
_DIRECTORY_RECORD_BASE_URL = "https://www.slough.gov.uk/directory-record"
_MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}
_DATE_RE = re.compile(r"(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})")
_BIN_TYPE_MAP = {
    "grey bin": "Grey bin",
    "red bin": "Red bin",
    "green bin": "Green bin",
    "food waste": "Food waste",
}


@dataclass(frozen=True, slots=True)
class _Record:
    id: int
    name: str


async def _parse_date_page(url: str, http: Http) -> list[date]:
    r = await http.get(url, timeout=30)
    page = soup(r.text)
    article = page.find("article")
    if article is None:
        return []

    dates: list[date] = []
    for li in article.find_all("li"):
        match = _DATE_RE.search(li.get_text(strip=True))
        if not match:
            continue
        day = int(match.group(1))
        month = _MONTHS.get(match.group(2).lower())
        year = int(match.group(3))
        if month is None:
            continue
        try:
            dates.append(date(year, month, day))
        except ValueError:
            continue
    return dates


async def _parse_record_page(record_id: int, http: Http) -> list[Collection]:
    url = f"{_DIRECTORY_RECORD_BASE_URL}/{record_id}/bin-day"
    r = await http.get(url, timeout=30)
    page = soup(r.text)

    dl = page.find("dl")
    if dl is None:
        raise AddressNotFound(f"No bin schedule for Slough directory record {record_id}")

    entries: list[Collection] = []
    for dt in dl.find_all("dt"):
        heading = dt.get_text(strip=True).lower()
        bin_label = next(
            (label for keyword, label in _BIN_TYPE_MAP.items() if keyword in heading),
            None,
        )
        if bin_label is None:
            continue

        dd = dt.find_next_sibling("dd")
        if dd is None:
            continue

        link = dd.find("a", href=re.compile(r"/bin-collections/"))
        if link is None:
            continue
        schedule_url = link["href"]
        if not schedule_url.startswith("http"):
            schedule_url = "https://www.slough.gov.uk" + schedule_url
        for collection_date in await _parse_date_page(schedule_url, http):
            entries.append(Collection(date=collection_date, type=bin_label))

    if not entries:
        raise AddressNotFound(f"No bin schedule for Slough directory record {record_id}")
    return entries


async def _search_records(street: str, http: Http) -> list[_Record]:
    r = await http.get(
        _DIRECTORY_SEARCH_URL,
        params={
            "directoryID": "30",
            "keywords": street,
            "submit": "Search",
        },
        timeout=30,
    )
    page = soup(r.text)

    results: list[_Record] = []
    for anchor in page.select("ul.list--record li.list__item a.list__link"):
        href = anchor.get("href", "")
        match = re.match(r"/directory-record/(\d+)/", href)
        if match:
            results.append(_Record(id=int(match.group(1)), name=text_of(anchor)))
    return results


def _narrow_by_number(results: list[_Record], house_number: str | None) -> list[_Record]:
    """Drop directory entries whose house-number range excludes the requested number."""
    match = re.match(r"\d+", house_number or "")
    if not match:
        return []
    number = int(match.group(0))
    kept: list[_Record] = []
    for record in results:
        range_match = re.match(r"(\d+)\s*-\s*(\d+)\b", record.name)
        if range_match and not int(range_match.group(1)) <= number <= int(range_match.group(2)):
            continue
        kept.append(record)
    return kept


class Slough(Scraper):
    meta = Meta(
        title=_TITLE,
        url=_URL,
        lads=("E06000039",),
        cases={
            "Knolton Way, Montgomery Place": {"record_id": "34771"},
            "Abbey Close (wheelie bins)": {"record_id": "34035"},
            "Anslow Place (communal bins)": {"record_id": "34069"},
        },
    )
    requires = frozenset()

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        record_id_value = address.get("record_id")
        if record_id_value is not None:
            try:
                record_id = int(record_id_value)
            except ValueError as exc:
                raise InputError("Slough record_id must be numeric") from exc
        else:
            street = address.street
            if street is None:
                raise InputError("Slough needs a record_id or street")
            results = await _search_records(street, http)
            if not results:
                raise AddressNotFound(f"No Slough directory records found for {street!r}")
            if len(results) == 1:
                record_id = results[0].id
            else:
                exact = [record for record in results if record.name.lower() == street.lower()]
                narrowed = _narrow_by_number(results, address.house_number)
                if len(exact) == 1:
                    record_id = exact[0].id
                elif len(narrowed) == 1:
                    record_id = narrowed[0].id
                else:
                    raise AddressNotFound(
                        f"Multiple Slough directory records found for {street!r}",
                        [record.name for record in results],
                    )

        return await _parse_record_page(record_id, http)


SCRAPER = Slough()
