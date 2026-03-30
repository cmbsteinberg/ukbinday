from datetime import datetime

from api.compat.ukbcd.common import *
from api.compat.ukbcd.get_bin_data import AbstractGetBinDataClass


class CouncilClass(AbstractGetBinDataClass):
    """
    Concrete classes have to implement all abstract operations of the base
    class. They can also override some operations with a default
    implementation.
    """

    def parse_data(self, page: str, **kwargs) -> dict:
        driver = None
        data = {"bins": []}
        try:
            user_uprn = kwargs.get("uprn")
            check_uprn(user_uprn)

            URI = "https://api.leeds.gov.uk/public/waste/v1/BinsDays"

            startDate = datetime.now()
            endDate = (startDate + timedelta(weeks=8)).strftime("%Y-%m-%d")
            startDate = startDate.strftime("%Y-%m-%d")

            params = {
                "uprn": user_uprn,
                "startDate": startDate,
                "endDate": endDate,
            }

            headers = {
                "ocp-apim-subscription-key": "ad8dd80444fe45fcad376f82cf9a5ab4",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36",
            }

            # print(params)

            # Send GET request
            response = httpx.get(URI, params=params, headers=headers)

            print(response.content)

            collections = json.loads(response.content)

            for collection in collections:

                collectionDate = datetime.strptime(
                    collection["date"], "%Y-%m-%dT%H:%M:%S"
                )

                data["bins"].append(
                    {
                        "type": collection["type"],
                        "collectionDate": collectionDate.strftime(date_format),
                    }
                )

        except Exception as e:
            # Here you can log the exception if needed
            print(f"An error occurred: {e}")
            # Optionally, re-raise the exception if you want it to propagate
            raise
        finally:
            # This block ensures that the driver is closed regardless of an exception
            if driver:
                driver.quit()
        return data


# --- Adapter for Project API ---
from api.compat.hacs import Collection  # type: ignore[attr-defined]

TITLE = "Leeds"
URL = "https://www.leeds.gov.uk/residents/bins-and-recycling/check-your-bin-day"
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
