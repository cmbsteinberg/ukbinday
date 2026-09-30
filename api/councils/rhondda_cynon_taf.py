"""Rhondda Cynon Taf: fetches collection calendars by UPRN, with printable and monthly-calendar fallbacks."""

from __future__ import annotations

from datetime import datetime

from bs4 import BeautifulSoup, Tag

from api.councils._base import Address, Collection, Http, Meta, Scraper, soup

_BIN_PAGE = (
    "https://www.rctcbc.gov.uk/EN/Resident/RecyclingandWaste/"
    "RecyclingandWasteCollectionDays.aspx"
)


def _extract_collections(calendar: Tag | BeautifulSoup) -> list[Collection]:
    calendar_month = calendar.find("div", {"class": "calendar-month"})
    if not isinstance(calendar_month, Tag):
        return []

    month = calendar_month.text.strip()
    calendar_days = calendar.find_all("div", {"class": "card-body card-body-padding"})
    entries: list[Collection] = []
    for day in calendar_days:
        pickups = day.find_all("a")
        if len(pickups) == 0:
            continue
        day_title = day.find("div", {"class": "card-title"})
        if not isinstance(day_title, Tag):
            continue
        collection_date = datetime.strptime(
            day_title.text.strip() + " " + month,
            "%d %B %Y",
        ).date()
        for pickup in pickups:
            entries.append(Collection(collection_date, pickup.text))
    return entries


def _extract_printable_calendar(page: BeautifulSoup) -> list[Collection] | None:
    printable_calendar = page.find("div", {"class": "printableCalendar"})
    if not isinstance(printable_calendar, Tag):
        return None

    calendars = printable_calendar.find_all("div", {"class": "calendar-wrap onlyPrint"})
    if not calendars:
        return None

    entries: list[Collection] = []
    for calendar in calendars:
        if isinstance(calendar, Tag):
            entries.extend(_extract_collections(calendar))
    return entries or None


class RhonddaCynonTaf(Scraper):
    meta = Meta(
        title="Rhondda Cynon Taf County Borough Council",
        url=_BIN_PAGE,
        lads=("W06000016",),
        cases={
            "Test_001": {"uprn": "10024274791"},
            "Test_002": {"uprn": "100100718352"},
            "Test_003": {"uprn": "100100733093"},
        },
    )
    requires = frozenset({"uprn"})

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        entries: list[Collection] = []
        for month in range(4):
            response = await http.get(
                f"{_BIN_PAGE}?uprn={address.need('uprn')}&month={month}"
            )
            page = soup(response.text)
            printable_entries = _extract_printable_calendar(page)
            if printable_entries:
                return printable_entries

            calendar = page.find("div", {"class": "monthlyCalendar"}) or page
            if isinstance(calendar, Tag):
                entries.extend(_extract_collections(calendar))

        return entries


SCRAPER = RhonddaCynonTaf()
