"""Dates the way UK council sites write them."""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta

from dateutil import parser as dateutil_parser

_ORDINAL = re.compile(r"(?<=\d)(st|nd|rd|th)\b", re.IGNORECASE)
_WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
# Two defaults differing in every field: a field that comes out different between
# the two parses was missing from the text. Leap years, so "29 February" parses.
_PROBE_A = datetime(2000, 1, 1)
_PROBE_B = datetime(2004, 2, 2)


def parse_date(text: str, *, today: date | None = None) -> date:
    """Parse a UK-style date: "Thursday 1st October", "01/10/2026", "1 Oct 26", "2026-10-01".

    Day comes before month. When the text has no year, the year is the one
    that puts the date closest to `today` (default: the real today), so
    "2 January" read on 30 December is next year's and "29 December" read on
    3 January is last year's. Raises `ValueError` for text without both a day
    and a month ("December TBC", "Monday").
    """
    cleaned = _ORDINAL.sub("", text).strip()
    iso = len(cleaned) >= 10 and cleaned[4] == "-" and cleaned[:4].isdigit()
    a = dateutil_parser.parse(cleaned, default=_PROBE_A, dayfirst=not iso, fuzzy=True)
    b = dateutil_parser.parse(cleaned, default=_PROBE_B, dayfirst=not iso, fuzzy=True)
    # fuzzy=True would otherwise read "December TBC" as 1 December, "Mon" as some Monday.
    if a.day != b.day or a.month != b.month:
        raise ValueError(f"No day and month in {text!r}")
    if a.year == b.year:
        return a.date()

    today = today or date.today()
    candidates = []
    for year in range(today.year - 4, today.year + 5):  # a leap year for 29 February
        try:
            candidates.append(date(year, a.month, a.day))
        except ValueError:  # 29 February in a common year
            continue
    return min(candidates, key=lambda d: abs((d - today).days))


def weekday_number(day: str | int) -> int:
    """Monday=0 ... Sunday=6, from a number or a (possibly abbreviated) English day name."""
    if isinstance(day, int):
        return day % 7
    key = day.strip().lower()[:3]
    for number, name in enumerate(_WEEKDAYS):
        if key and name.startswith(key):
            return number
    raise ValueError(f"Not a weekday: {day!r}")


def next_weekday(day: str | int, *, after: date | None = None, include_today: bool = True) -> date:
    """The next date falling on `day`, counting from `after` (default today)."""
    start = after or date.today()
    ahead = (weekday_number(day) - start.weekday()) % 7
    if ahead == 0 and not include_today:
        ahead = 7
    return start + timedelta(days=ahead)


def every(start: date, *, days: int, count: int) -> list[date]:
    """`count` dates from `start`, `days` apart: weekly rounds are `every(d, days=7, count=8)`."""
    return [start + timedelta(days=days * i) for i in range(count)]
