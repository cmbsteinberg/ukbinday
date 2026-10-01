"""Coventry: search for a street, follow its directory record, and read its collection calendar."""

from __future__ import annotations

import logging
import re
from datetime import date, datetime

from api.councils._base import (
    Address,
    AddressNotFound,
    Collection,
    Http,
    Meta,
    Scraper,
    UpstreamError,
    soup,
)

_API_URLS = {
    "search": "https://www.coventry.gov.uk/directory/search",
    "directory_record": "https://www.coventry.gov.uk",
}
_LOGGER = logging.getLogger(__name__)


def _normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("\xa0", " ")).strip()


class Coventry(Scraper):
    meta = Meta(
        title="Coventry City Council",
        url="https://www.coventry.gov.uk/bin-collection-calendar",
        lads=("E08000026",),
        cases={
            "Test_001": {"street": "Linwood Drive"},
            "Test_002": {"street": "Cromwell Lane"},
            "Test_003": {"street": "Lutterworth Road"},
        },
    )
    requires = frozenset({"street"})
    needs_browser = "Coventry's bin-day search is behind a reCAPTCHA."
    headers = {"user-agent": "Mozilla/5.0"}

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        street = address.need("street")

        params = {
            "directoryID": "82",
            "showInMap": "",
            "keywords": street,
            "search": "Search",
        }
        r = await http.get(_API_URLS["search"], params=params, timeout=30)
        page = soup(r.text)
        directory_record: str | None = None
        for link in page.find_all("a", {"class": "list__link"}):
            if street.upper() in link.text.upper():
                directory_record = str(link["href"])
                break

        if directory_record is None:
            raise AddressNotFound(f"Street {street!r} not found")

        r = await http.get(
            _API_URLS["directory_record"] + directory_record,
            timeout=30,
        )
        page = soup(r.text)
        schedule: str | None = None
        for button in page.find_all("a", {"class": "button"}):
            if "bin" in button["href"]:
                schedule = str(button["href"])
                break

        if schedule is None:
            raise UpstreamError(f"No bin collection calendar link found for {street!r}")

        r = await http.get(schedule, timeout=30)
        page = soup(r.text)
        entries: list[Collection] = []

        today = date.today()
        for table in page.select("div.editor table"):
            heading = table.find_previous(["h2", "h3"])
            year_match = re.search(r"\b(20\d{2})\b", heading.get_text() if heading else "")
            if year_match is None:
                continue
            year = year_match.group(1)

            headers = [
                _normalize_space(cell.get_text(" ", strip=True))
                for cell in table.select("thead th")
            ]
            if len(headers) < 2:
                continue

            for row in table.select("tbody tr"):
                cells = row.find_all(["th", "td"])
                if len(cells) != len(headers):
                    continue
                date_text = _normalize_space(cells[0].get_text(" ", strip=True))
                try:
                    waste_date = datetime.strptime(
                        f"{date_text} {year}", "%A %d %B %Y"
                    ).date()
                except ValueError:
                    _LOGGER.warning(
                        "Could not parse Coventry collection date '%s'", date_text
                    )
                    continue
                if waste_date < today:
                    continue

                for waste_type, cell in zip(headers[1:], cells[1:], strict=True):
                    if not re.search(r"\byes\b", cell.get_text(" ", strip=True), re.I):
                        continue
                    entries.append(Collection(date=waste_date, type=waste_type))

        return entries


SCRAPER = Coventry()
