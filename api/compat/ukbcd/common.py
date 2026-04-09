"""Lightweight shim for uk_bin_collection.uk_bin_collection.common.

Provides the helpers that RobBrad scrapers import via ``from ... common import *``
without pulling in heavy dependencies (selenium, pandas, etc.).
"""

import json  # noqa E401
import re
from datetime import datetime, timedelta
from enum import Enum

import httpx  # noqa: E401, F401 -- re-exported so robbrad scrapers get it via ``import *``
from dateutil.parser import parse

date_format = "%d/%m/%Y"

days_of_week = {
    "Monday": 0,
    "Tuesday": 1,
    "Wednesday": 2,
    "Thursday": 3,
    "Friday": 4,
    "Saturday": 5,
    "Sunday": 6,
}


class Region(Enum):
    ENG = 1
    NIR = 2
    SCT = 3
    WLS = 4


def check_postcode(postcode: str):
    if postcode is None or postcode.strip() == "":
        raise ValueError("Invalid postcode")
    return True


def check_paon(paon: str):
    if paon is None:
        raise ValueError("Invalid house number")
    return True


def check_uprn(uprn: str):
    if uprn is None or str(uprn).strip() == "":
        raise ValueError("Invalid UPRN")
    return True


def check_usrn(usrn: str):
    if usrn is None or str(usrn).strip() == "":
        raise ValueError("Invalid USRN")
    return True


def get_date_with_ordinal(date_number: int) -> str:
    return str(date_number) + (
        "th"
        if 4 <= date_number % 100 <= 20
        else {1: "st", 2: "nd", 3: "rd"}.get(date_number % 10, "th")
    )


def has_numbers(input_string: str) -> bool:
    return any(char.isdigit() for char in input_string)


def remove_ordinal_indicator_from_date_string(date_string: str) -> str:
    return re.sub(r"(?<=\d)(st|nd|rd|th)", "", date_string)


def parse_header(raw_header: str) -> dict:
    header = {}
    for line in raw_header.split("|"):
        if line.startswith(":"):
            a, b = line[1:].split(":", 1)
            a = f":{a}"
        else:
            a, b = line.split(":", 1)
        header[a.strip()] = b.strip()
    return header


def contains_date(string, fuzzy=False) -> bool:
    try:
        parse(string, fuzzy=fuzzy)
        return True
    except ValueError:
        return False


def remove_alpha_characters(input_string: str) -> str:
    return "".join(c for c in input_string if c.isdigit() or c == " ")


def get_weekday_dates_in_period(start: datetime, day_of_week: int, amount=8) -> list:
    """Return dates of a given weekday from start for ``amount`` weeks (no pandas)."""
    # Advance to the first occurrence of day_of_week
    current = start
    while current.weekday() != day_of_week:
        current += timedelta(days=1)
    results = []
    for _ in range(amount):
        results.append(current.strftime(date_format))
        current += timedelta(weeks=1)
    return results


def get_dates_every_x_days(start: datetime, step: int, amount: int = 8) -> list:
    results = []
    current = start
    for _ in range(amount):
        results.append(current.strftime(date_format))
        current += timedelta(days=step)
    return results


def get_next_occurrence_from_day_month(date: datetime) -> datetime:
    current_date = datetime.now()
    target_day = date.day
    target_month = date.month
    if (target_month < current_date.month) or (
        target_month == current_date.month and target_day < current_date.day
    ):
        try:
            date = date.replace(year=date.year + 1)
        except ValueError:
            date = date.replace(year=date.year + 1, day=28)
    return date


def get_next_day_of_week(day_name, fmt="%d/%m/%Y"):
    _days = [
        "Monday",
        "Tuesday",
        "Wednesday",
        "Thursday",
        "Friday",
        "Saturday",
        "Sunday",
    ]
    today = datetime.now()
    target_idx = _days.index(day_name)
    days_until = (target_idx - today.weekday()) % 7
    if days_until == 0:
        days_until = 7
    return (today + timedelta(days=days_until)).strftime(fmt)
