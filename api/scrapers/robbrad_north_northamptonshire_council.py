from datetime import datetime as dtm
from datetime import timedelta

from api.compat.ukbcd.common import *
from api.compat.ukbcd.get_bin_data import AbstractGetBinDataClass


def myFunc(e):
    return e["start"]


class CouncilClass(AbstractGetBinDataClass):
    """
    Concrete classes have to implement all abstract operations of the
    base class. They can also override some operations with a default
    implementation.
    """

    def parse_data(self, page: str, **kwargs) -> dict:
        data = {"bins": []}
        uprn = kwargs.get("uprn")
        check_uprn(uprn)
        today = int(datetime.now().timestamp()) * 1000
        dateforurl = datetime.now().strftime("%Y-%m-%d")
        dateforurl2 = (datetime.now() + timedelta(days=42)).strftime("%Y-%m-%d")
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 6.1; Win64; x64)",
        }
        pass  # urllib3 warnings disabled

        # Get variables for workings
        response = httpx.get(
            f"https://cms.northnorthants.gov.uk/bin-collection-search/calendarevents/{uprn}/{dateforurl}/{dateforurl2}",
            headers=headers,
        )
        if response.status_code != 200:
            raise ValueError("No bin data found for provided UPRN..")

        json_response = json.loads(response.text)

        output_dict = [
            x
            for x in json_response
            if int("".join(filter(str.isdigit, x["start"]))) >= today
        ]

        output_json = output_dict
        output_json.sort(key=myFunc)

        i = 0
        while i < len(output_json):
            sov = output_json[i]["title"].lower()
            if "recycling" in sov:
                bin_type = "Recycling"
            elif "garden" in sov:
                bin_type = "Garden"
            elif "refuse" in sov:
                bin_type = "General"
            else:
                bin_type = "Unknown"
            dateofbin = int("".join(filter(str.isdigit, output_json[i]["start"])))
            day = dtm.fromtimestamp(dateofbin / 1000)
            collection_data = {
                "type": bin_type,
                "collectionDate": day.strftime(date_format),
            }
            data["bins"].append(collection_data)
            i += 1

        return data


# --- Adapter for Project API ---
from api.compat.hacs import Collection  # type: ignore[attr-defined]

TITLE = "North Northamptonshire"
URL = "https://cms.northnorthants.gov.uk/bin-collection-search/calendarevents/100031021318/2023-10-17/2023-10-01"
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
