import logging
import time
from datetime import datetime

import httpx

from api.compat.ukbcd.common import *
from api.compat.ukbcd.get_bin_data import AbstractGetBinDataClass

logger = logging.getLogger(__name__)


# import the wonderful Beautiful Soup and the URL grabber
class CouncilClass(AbstractGetBinDataClass):
    """
    Concrete classes have to implement all abstract operations of the
    base class. They can also override some operations with a default
    implementation.
    """

    SESSION_URL = "https://my.sandwell.gov.uk/authapi/isauthenticated?uri=https%253A%252F%252Fmy.sandwell.gov.uk%252Fen%252F..."
    API_URL = "https://my.sandwell.gov.uk/apibroker/runLookup"
    HEADERS = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": "https://my.sandwell.gov.uk/fillform/?iframe_id=fillform-frame-1&db_id=",
    }
    LOOKUPS = [
        ("686295a88a750", "GWDate", ["Garden Waste (Green)"]),
        ("686294de50729", "DWDate", ["Household Waste (Grey)"]),
        ("6863a78a1dd8e", "FWDate", ["Food Waste (Brown)"]),
        ("68629dd642423", "MDRDate", ["Recycling (Blue)"]),
    ]

    def parse_data(self, page: str, **kwargs) -> dict:
        """
        Parse bin collection data for a given UPRN using the Sandwell API.

        Args:
            page (str): Unused HTML page content.
            **kwargs: Must include 'uprn'.

        Returns:
            dict: A dictionary with bin collection types and dates.
        """
        user_uprn = kwargs.get("uprn")
        check_uprn(user_uprn)
        bindata = {"bins": []}

        session = httpx.Client(follow_redirects=True)
        # Establish a session and grab the session ID
        r = session.get(self.SESSION_URL)
        r.raise_for_status()
        session_data = r.json()
        sid = session_data["auth-session"]
        timestamp = str(int(time.time() * 1000))

        payload = {
            "formValues": {
                "Property details": {
                    "Uprn": {
                        "value": user_uprn,
                    },
                    "NextCollectionFromDate": {
                        "value": datetime.today().strftime("%Y-%m-%d")
                    },
                },
            },
        }
        base_params = {
            "repeat_against": "",
            "noRetry": "false",
            "getOnlyTokens": "undefined",
            "log_id": "",
            "app_name": "AF-Renderer::Self",
            # unix_timestamp
            "_": timestamp,
            "sid": sid,
        }
        # (request_id, date field to use from response, bin type labels)

        for request_id, date_key, bin_types in self.LOOKUPS:
            params = {"id": request_id, **base_params}

            try:
                resp = session.post(
                    self.API_URL, json=payload, headers=self.HEADERS, params=params
                )
                resp.raise_for_status()
                result = resp.json()

                rows_data = result["integration"]["transformed"]["rows_data"]

                if not isinstance(rows_data, dict):
                    logger.warning("Unexpected rows_data format: %s", rows_data)
                    continue

                for row in rows_data.values():
                    date = row.get(date_key)
                    if not date:
                        logger.warning(
                            "Date key '%s' missing in row: %s", date_key, row
                        )
                        continue

                    for bin_type in bin_types:
                        bindata["bins"].append(
                            {"type": bin_type, "collectionDate": date}
                        )

            except httpx.HTTPError as e:
                logger.error("API request failed: %s", e)
                continue
            except (KeyError, ValueError, TypeError) as e:
                logger.warning("Unexpected structure in response: %s", e)
                continue

        logger.info("Parsed bins: %s", bindata["bins"])
        return bindata


# --- Adapter for Project API ---
from api.compat.hacs import Collection  # type: ignore[attr-defined]

TITLE = "Sandwell"
URL = "https://www.sandwell.gov.uk"
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
