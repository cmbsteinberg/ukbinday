import re
from datetime import date, timedelta

from bs4 import BeautifulSoup
from dateutil.parser import parse

from api.compat.curl_cffi_fallback import AsyncClient as _CurlCffiClient
from api.compat.hacs import Collection, Icons  # type: ignore[attr-defined]

TITLE = "Islington Council"
DESCRIPTION = "Source for Islington Council, UK."
URL = "https://www.islington.gov.uk"
TEST_CASES = {
    "Test_001": {"postcode": "n1 1xr", "uprn": "5300094897"},
    "Test_002": {"postcode": "N1 0DD", "uprn": 10001295652},
    "Test_003": {"postcode": "N19 4TA", "uprn": "5300078702"},
}
ICON_MAP = {
    "Green recycling box": Icons.RECYCLING,
    "Dry recycling bin": Icons.RECYCLING,
    "Communal dry recycling bin": Icons.RECYCLING,
    "Small kitchen waste box": Icons.BIO_KITCHEN,
    "Large brown kitchen waste box": Icons.BIO_KITCHEN,
    "Reuseable garden waste sack": Icons.GARDEN,
    "Household refuse sack": Icons.GENERAL_WASTE,
    "Refuse skip": Icons.COMMERCIAL,
    "Food waste recycling": Icons.BIO_KITCHEN,
    "Mixed dry recycling": Icons.RECYCLING,
    "Non-recyclable rubbish": Icons.GENERAL_WASTE,
}

WEEKDAYS = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}
RULE_RE = re.compile(r"^(.*?) - .*?collected every week on (.+?)\.?$", re.IGNORECASE)
WEEKS_AHEAD = 12


class Source:
    def __init__(self, postcode, uprn):
        self._uprn = str(uprn)
        self._postcode = str(postcode)
        self._session = _CurlCffiClient(follow_redirects=True)

    async def fetch(self):
        url = f"https://www.islington.gov.uk/your-area?Postcode={self._postcode}&Uprn={self._uprn}"

        response = await self._session.get(url)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")

        entries = []

        heading = soup.find(string="Waste and recycling collections")
        if heading is None:
            raise ValueError("Waste and recycling collections section not found")
        content = heading.find_next("div", class_="m-toggle-content")
        if content is None:
            raise ValueError("Waste and recycling collections content not found")

        waste_table = content.find("table")
        if waste_table:
            for row in waste_table.find_all("tr"):
                waste_type = row.find("td").text.strip().split(",")[0].split(" - ")[0]
                collection_day = (
                    row.find("td").text.strip().split(",")[1].split(" on ")[1]
                )

                entries.append(
                    Collection(
                        date=parse(collection_day).date(),
                        t=waste_type,
                        icon=ICON_MAP.get(waste_type),
                    )
                )
            return entries

        # The page now lists weekly rules rather than dated collections, e.g.
        # "Mixed dry recycling - recycling container, collected every week on
        # Thursday, Saturday". Expand each rule into upcoming dates.
        today = date.today()
        seen: set[tuple[str, int]] = set()
        for li in content.find_all("li"):
            text = " ".join(li.get_text().split())
            m = RULE_RE.match(text)
            if not m:
                continue
            waste_type = m.group(1).strip()
            days = [
                WEEKDAYS[d.strip().lower()]
                for d in m.group(2).split(",")
                if d.strip().lower() in WEEKDAYS
            ]
            for weekday in days:
                if (waste_type, weekday) in seen:
                    continue
                seen.add((waste_type, weekday))
                first = today + timedelta(days=(weekday - today.weekday()) % 7)
                for week in range(WEEKS_AHEAD):
                    entries.append(
                        Collection(
                            date=first + timedelta(weeks=week),
                            t=waste_type,
                            icon=ICON_MAP.get(waste_type),
                        )
                    )

        return entries
