from datetime import datetime, timedelta

from api.compat.hacs import Collection  # type: ignore[attr-defined]

TITLE = "City of Edinburgh Council"
DESCRIPTION = "Source for edinburgh.gov.uk waste collection."
URL = "https://www.edinburgh.gov.uk"
# house_number = collection day (e.g. "Tuesday"), postcode = week label (e.g. "Week 1")
TEST_CASES = {
    "Test_001": {"house_number": "Tuesday", "postcode": "Week 1"},
}

DAYS_OF_WEEK = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
COLLECTION_WEEKS = ["Week 1", "Week 2"]

# Rota anchor dates — update these when Edinburgh publishes new rota cycles
WEEK_1_RECYCLING_START = datetime(2025, 11, 3)
WEEK_1_GLASS_START = datetime(2025, 11, 3)
WEEK_1_REFUSE_START = datetime(2025, 11, 10)
WEEK_2_RECYCLING_START = datetime(2025, 11, 10)
WEEK_2_GLASS_START = datetime(2025, 11, 10)
WEEK_2_REFUSE_START = datetime(2025, 11, 3)

ICON_MAP = {
    "Grey Bin": "mdi:trash-can",
    "Green Bin": "mdi:recycle",
    "Glass Box": "mdi:glass-fragile",
}


def _dates_every_n_days(start: datetime, interval: int, count: int) -> list[datetime]:
    today = datetime.now()
    dates = []
    d = start
    while d < today:
        d += timedelta(days=interval)
    for _ in range(count):
        dates.append(d)
        d += timedelta(days=interval)
    return dates


class Source:
    def __init__(self, house_number: str | None = None, postcode: str | None = None):
        self._collection_day = house_number or "Monday"
        self._collection_week = postcode or "Week 1"

    async def fetch(self) -> list[Collection]:
        week_idx = COLLECTION_WEEKS.index(self._collection_week)
        offset_days = DAYS_OF_WEEK.index(self._collection_day)

        if week_idx == 0:
            recycling_start = WEEK_1_RECYCLING_START
            glass_start = WEEK_1_GLASS_START
            refuse_start = WEEK_1_REFUSE_START
        else:
            recycling_start = WEEK_2_RECYCLING_START
            glass_start = WEEK_2_GLASS_START
            refuse_start = WEEK_2_REFUSE_START

        entries = []
        for bin_type, start in [
            ("Grey Bin", refuse_start),
            ("Green Bin", recycling_start),
            ("Glass Box", glass_start),
        ]:
            for d in _dates_every_n_days(start, 14, 4):
                collection_date = (d + timedelta(days=offset_days)).date()
                entries.append(
                    Collection(
                        date=collection_date,
                        t=bin_type,
                        icon=ICON_MAP.get(bin_type),
                    )
                )

        return sorted(entries, key=lambda c: c.date)
