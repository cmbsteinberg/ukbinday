from api.compat.ukbcd.councils.WestMorlandAndFurness import (
    CouncilClass as WestMorlandAndFurnessCouncilClass,
)


class CouncilClass(WestMorlandAndFurnessCouncilClass):
    """
    Eden District Council was absorbed into Westmorland and Furness
    Council. Eden's own self-service page no longer shows collection
    days directly - it just links out to Westmorland and Furness's
    waste-collection-schedule tool, which already serves the same UPRNs.
    """


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
        from datetime import datetime

        kwargs = {}
        if self.uprn: kwargs['uprn'] = self.uprn

        data = await self._scraper.parse_data("", **kwargs)

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
