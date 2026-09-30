"""Merthyr Tydfil: postcode lookup at the council's Umbraco endpoint, returning weekly or fortnightly collection dates."""

from __future__ import annotations

import re
from datetime import date, timedelta

from api.councils._base import (
    Address,
    Collection,
    Http,
    Meta,
    Scraper,
    UpstreamError,
    soup,
)

_API_URL = "https://www.merthyr.gov.uk/umbraco/Surface/BinDaySurface/GetCollectionDay"
_DAYS_OF_WEEK = (
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
)


def _next_occurrence(day_name: str) -> date:
    """Return the next occurrence of day_name, excluding today."""
    today = date.today()
    target_idx = _DAYS_OF_WEEK.index(day_name)
    today_idx = today.weekday()
    days_ahead = (target_idx - today_idx) % 7
    if days_ahead == 0:
        days_ahead = 7
    return today + timedelta(days=days_ahead)


def _next_fortnightly(day_name: str, current_week: str, bin_week: str) -> date:
    """Return the next fortnightly collection date."""
    today = date.today()
    target_idx = _DAYS_OF_WEEK.index(day_name)
    today_idx = today.weekday()

    days_ahead = (target_idx - today_idx) % 7
    if days_ahead == 0:
        days_ahead = 7

    in_same_week = (today_idx + days_ahead) <= 6
    if in_same_week:
        candidate_week = current_week
    else:
        candidate_week = "two" if current_week == "one" else "one"

    if candidate_week != bin_week:
        days_ahead += 7

    return today + timedelta(days=days_ahead)


class MerthyrTydfil(Scraper):
    meta = Meta(
        title="Merthyr Tydfil County Borough",
        url="https://www.merthyr.gov.uk",
        lads=("W06000024",),
        cases={},
    )
    requires = frozenset({"postcode"})
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/134.0.0.0 Safari/537.36"
        )
    }

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        response = await http.post(
            _API_URL,
            data={"postcode": address.need("postcode")},
            headers={
                "X-Requested-With": "XMLHttpRequest",
                "Referer": (
                    "https://www.merthyr.gov.uk/resident/bins-and-recycling/"
                    "check-your-collection-day/"
                ),
            },
            timeout=30,
        )
        page = soup(response.text)

        h4 = page.find("h4")
        if h4 and "No results" in h4.get_text():
            return []

        h5 = page.find("h5")
        if not h5:
            raise UpstreamError("Could not determine current week from Merthyr response")
        current_week_strong = h5.find("strong")
        if not current_week_strong:
            raise UpstreamError("Could not parse current week indicator")
        current_week = current_week_strong.get_text(strip=True).lower()

        collections: list[Collection] = []
        for p_tag in page.find_all("p"):
            text = p_tag.get_text()
            strong_tags = p_tag.find_all("strong")

            if not strong_tags:
                continue

            day_name = strong_tags[0].get_text(strip=True)
            if day_name not in _DAYS_OF_WEEK:
                continue

            text_lower = text.lower()
            if "recycling" in text_lower:
                bin_type = "Recycling"
            elif "household waste" in text_lower:
                bin_type = "Household Waste"
            elif "garden waste" in text_lower:
                bin_type = "Garden Waste"
            else:
                match = re.match(r"Your (.+?) collection day", text)
                bin_type = match.group(1).strip().title() if match else "Unknown"

            if "every week" in text_lower:
                base = _next_occurrence(day_name)
                for i in range(4):
                    collections.append(Collection(base + timedelta(weeks=i), bin_type))
            else:
                bin_week_strong = strong_tags[-1] if len(strong_tags) > 1 else None
                if not bin_week_strong:
                    continue
                bin_week = bin_week_strong.get_text(strip=True).lower()

                base = _next_fortnightly(day_name, current_week, bin_week)
                for i in range(2):
                    collections.append(Collection(base + timedelta(weeks=i * 2), bin_type))

        return collections


SCRAPER = MerthyrTydfil()
