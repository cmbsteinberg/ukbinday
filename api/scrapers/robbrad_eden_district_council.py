import httpx
from bs4 import BeautifulSoup

from api.compat.ukbcd.common import *
from api.compat.ukbcd.get_bin_data import AbstractGetBinDataClass


class CouncilClass(AbstractGetBinDataClass):
    """
    Concrete classes have to implement all abstract operations of the
    base class. They can also override some operations with a default
    implementation.
    """

    def parse_data(self, page: str, **kwargs) -> dict:

        user_uprn = kwargs.get("uprn")
        check_uprn(user_uprn)
        bindata = {"bins": []}

        URI = f"https://my.eden.gov.uk/myeden.aspx?action=SetAddress&UniqueId={user_uprn}"

        headers = {
            "user-agent": "Mozilla/5.0",
        }

        response = httpx.get(URI, headers=headers)
        soup = BeautifulSoup(response.text, "html.parser")

        # Find the Refuse and Recycling panel by looking for the heading
        refuse_heading = soup.find("h3", {"id": "Refuse_and_Recycling"})

        if not refuse_heading:
            # Try alternative search
            refuse_heading = soup.find("h3", string=lambda text: text and "Refuse" in text)

        if not refuse_heading:
            return bindata

        # Find the parent panel and then the panel data
        refuse_panel = refuse_heading.find_parent("div", {"class": "atPanel"})

        if not refuse_panel:
            return bindata

        # Extract collection day information
        panel_data = refuse_panel.find("div", {"class": "atPanelData"})

        if not panel_data:
            return bindata

        # Parse the collection days text
        # The HTML uses <br> tags, so we need to parse differently
        # Format: "<strong> Blue refuse bags:</strong> Wednesday <br>"
        collection_info = {}

        # Get all the text and split by <br> tags
        html_content = str(panel_data)

        # Extract bin types and days using regex or simple parsing
        import re
        # Pattern: <strong>BIN_TYPE:</strong> DAY
        pattern = r'<strong>\s*([^:]+):</strong>\s*([^<\n]+)'
        matches = re.findall(pattern, html_content)

        for bin_type, day in matches:
            # Clean up whitespace in bin type and day names
            bin_type = ' '.join(bin_type.split())
            day = ' '.join(day.split())
            if day and day not in ['download', 'recycling calendar']:
                collection_info[bin_type] = day

        # Get current date and find next collection dates
        current_date = datetime.now()

        # Map day names to weekday numbers (Monday=0, Sunday=6)
        day_map = {
            "Monday": 0,
            "Tuesday": 1,
            "Wednesday": 2,
            "Thursday": 3,
            "Friday": 4,
            "Saturday": 5,
            "Sunday": 6
        }

        # Generate next 12 weeks of collections
        for bin_type, day_name in collection_info.items():
            if day_name in day_map:
                target_weekday = day_map[day_name]

                # Find next occurrence of this weekday
                days_ahead = target_weekday - current_date.weekday()
                if days_ahead <= 0:  # Target day already happened this week
                    days_ahead += 7

                next_date = current_date + timedelta(days=days_ahead)

                # Add next 12 collections (weekly)
                for week in range(12):
                    collection_date = next_date + timedelta(weeks=week)
                    dict_data = {
                        "type": bin_type,
                        "collectionDate": collection_date.strftime(date_format),
                    }
                    bindata["bins"].append(dict_data)

        # Sort by date
        bindata["bins"].sort(
            key=lambda x: datetime.strptime(x.get("collectionDate"), date_format)
        )

        return bindata


# --- Adapter for Project API ---
from api.compat.hacs import Collection  # type: ignore[attr-defined]

TITLE = "Eden District (Westmorland and Furness)"
URL = "https://my.eden.gov.uk/myeden.aspx"
TEST_CASES = {}


class Source:
    def __init__(self, uprn: str | None = None):
        self.uprn = uprn
        self._scraper = CouncilClass()

    async def fetch(self) -> list[Collection]:
        import asyncio
        from datetime import datetime

        kwargs = {}
        if self.uprn: kwargs['uprn'] = self.uprn

        def _run():
            page = ""
            if hasattr(self._scraper, "parse_data"):
                return self._scraper.parse_data(page, **kwargs)
            raise NotImplementedError("Could not find parse_data on scraper")

        data = await asyncio.to_thread(_run)

        entries = []
        if isinstance(data, dict) and "bins" in data:
            for item in data["bins"]:
                bin_type = item.get("type")
                date_str = item.get("collectionDate")
                if not bin_type or not date_str:
                    continue
                try:
                    if "-" in date_str:
                        dt = datetime.strptime(date_str, "%Y-%m-%d").date()
                    elif "/" in date_str:
                        dt = datetime.strptime(date_str, "%d/%m/%Y").date()
                    else:
                        continue
                    entries.append(Collection(date=dt, t=bin_type, icon=None))
                except ValueError:
                    continue
        return entries
