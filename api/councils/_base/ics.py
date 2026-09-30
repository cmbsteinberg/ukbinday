"""iCalendar feeds: expand a council's .ics into dated events."""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, timedelta
from typing import Any, NamedTuple

from icalevents import icalevents


class IcsEvent(NamedTuple):
    date: date
    summary: str
    description: str | None = None


def _repair(ics: str) -> str:
    """Fix malformed feeds that councils really publish."""
    # All-day EXDATEs next to timed DTSTARTs make dateutil compare date with datetime.
    ics = re.sub(r"(EXDATE;VALUE=DATE:[0-9]+)\r?\n", lambda m: m.group(1) + "T010000\n", ics)
    # "DTSTART;TZID=Europe/London:20260505T" with the time missing.
    ics = re.sub(r"(DT(?:START|END)[^:]*:\d{8})T(\r?\n)", r"\g<1>T000000\g<2>", ics)
    # TZID on an all-day value is invalid and makes recurrences timezone-aware
    # while EXDATEs stay naive.
    return re.sub(r"(DT(?:START|END));TZID=[^;:]+;(VALUE=DATE:)", r"\1;\2", ics)


def parse_ics(ics: str, *, days: int = 365) -> list[IcsEvent]:
    """Events from today to `days` ahead, recurrences expanded, in feed order."""
    start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    events: list[Any] = icalevents.events(
        start=start, end=start + timedelta(days=days), string_content=_repair(ics).encode()
    )
    # Replacement instances (RECURRENCE-ID) sometimes omit SUMMARY and expect
    # the parent's.
    parent_summary = {e.uid: e.summary for e in events if e.summary and e.recurring}
    out: list[IcsEvent] = []
    for e in events:
        summary = e.summary or parent_summary.get(e.uid)
        if not summary:
            continue
        day = e.start.date() if isinstance(e.start, datetime) else e.start
        description = e.description.strip() if isinstance(e.description, str) and e.description.strip() else None
        out.append(IcsEvent(day, summary.strip(), description))
    return out
