import itertools

from bs4 import BeautifulSoup, Tag
from dateutil.parser import parse as date_parse

from api.compat.ukbcd.common import *
from api.compat.ukbcd.get_bin_data import AbstractGetBinDataClass
import httpx


class CouncilClass(AbstractGetBinDataClass):

    def parse_data(self, page: str, **kwargs) -> dict:
        data = {"bins": []}
        user_uprn = kwargs.get("uprn")

        api_url = f"https://maps.westsuffolk.gov.uk/MyWestSuffolk.aspx?action=SetAddress&UniqueId={user_uprn}"

        response = httpx.get(api_url)

        soup = BeautifulSoup(response.text, features="html.parser")
        soup.prettify()

        def panel_search(cur_tag: Tag):
            """
            Helper function to find the correct tag
            """
            if cur_tag.name != "div":
                return False

            tag_class = cur_tag.attrs.get("class", None)
            if tag_class is None:
                return False

            parent_has_header = cur_tag.parent.find_all(
                "h4", string="Bin collection days"
            )
            if len(parent_has_header) < 1:
                return False

            return "atPanelData" in tag_class

        collection_tag = soup.body.find_all(panel_search)

        # Parse the resultant div
        for tag in collection_tag:
            text_list = list(tag.stripped_strings)
            
            # Filter out any empty strings or whitespace-only entries
            text_list = [text.strip() for text in text_list if text.strip()]
            
            # Check if we have an even number of elements
            if len(text_list) % 2 != 0:
                # If odd number, log warning and skip the last element
                # This handles cases where there's extra text or a missing date
                text_list = text_list[:-1]
            
            # Create and parse the list as tuples of name:date
            for bin_name, collection_date in itertools.batched(text_list, 2):
                try:
                    # Clean-up the bin_name
                    bin_name_clean = (
                        bin_name.strip()
                        .replace("\r", "")
                        .replace("\n", "")
                        .replace(":", "")
                    )
                    bin_name_clean = re.sub(" +", " ", bin_name_clean)

                    # Get the bin colour
                    bin_colour = "".join(re.findall(r"^(.*) ", bin_name_clean))

                    # Parse the date
                    next_collection = date_parse(collection_date)
                    next_collection = next_collection.replace(year=datetime.now().year)

                    dict_data = {
                        "type": bin_name_clean,
                        "collectionDate": next_collection.strftime(date_format),
                    }

                    data["bins"].append(dict_data)

                except Exception as ex:
                    raise ValueError(f"Error parsing bin data: {ex}")

        return data


# --- Adapter for Project API ---
from api.compat.hacs import Collection  # type: ignore[attr-defined]

TITLE = "West Suffolk"
URL = "https://maps.westsuffolk.gov.uk/MyWestSuffolk.aspx"
TEST_CASES = {}


class Source:
    def __init__(self, uprn: str | None = None, postcode: str | None = None):
        self.uprn = uprn
        self.postcode = postcode
        self._scraper = CouncilClass()

    async def fetch(self) -> list[Collection]:
        import asyncio
        from datetime import datetime

        kwargs = {}
        if self.uprn: kwargs['uprn'] = self.uprn
        if self.postcode: kwargs['postcode'] = self.postcode

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
