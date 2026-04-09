import httpx
from bs4 import BeautifulSoup

from api.compat.ukbcd.common import *
from api.compat.ukbcd.get_bin_data import AbstractGetBinDataClass


# import the wonderful Beautiful Soup and the URL grabber
class CouncilClass(AbstractGetBinDataClass):
    """
    Concrete classes have to implement all abstract operations of the
    base class. They can also override some operations with a default
    implementation.
    """

    def parse_data(self, page: str, **kwargs) -> dict:
        user_uprn = kwargs.get("uprn")
        check_uprn(user_uprn)

        # UPRN is passed in via a cookie. Set cookies/params and GET the page
        cookies = {
            "SVBINZONE": f"VALE%3AUPRN%40{user_uprn}",
        }
        headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
            "Accept-Language": "en-GB,en;q=0.7",
            "Cache-Control": "max-age=0",
            "Connection": "keep-alive",
            "Referer": "https://eform.whitehorsedc.gov.uk/ebase/BINZONE_DESKTOP.eb?SOVA_TAG=VALE&ebd=0&ebz=1_1704201201813",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-User": "?1",
            "Sec-GPC": "1",
            "Upgrade-Insecure-Requests": "1",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36",
        }
        params = {
            "SOVA_TAG": "VALE",
            "ebd": "0",
        }
        pass  # urllib3 warnings disabled
        response = httpx.get(
            "https://eform.whitehorsedc.gov.uk/ebase/BINZONE_DESKTOP.eb",
            params=params,
            headers=headers,
            cookies=cookies,
        )

        # Parse response text for super speedy finding
        soup = BeautifulSoup(response.text, features="html.parser")
        soup.prettify()

        data = {"bins": []}

        current_year = datetime.now().year
        next_year = current_year + 1

        # Page has slider info side by side, which are two instances of this class
        for bin in soup.find_all("div", {"class": "bintxt"}):
            try:
                # Check bin type heading and make that bin type and colour
                bin_type_info = list(bin.stripped_strings)
                if "rubbish" in bin_type_info[0]:
                    bin_type = "Rubbish"
                    bin_colour = "Black"
                elif "recycling" in bin_type_info[0]:
                    bin_type = "Recycling"
                    bin_colour = "Green"
                else:
                    raise ValueError(f"No bin info found in {bin_type_info[0]}")

                bin_date_info = list(
                    bin.find_next("div", {"class": "binextra"}).stripped_strings
                )
                # On standard collection schedule, date will be contained in the first string
                if contains_date(bin_date_info[0]):
                    bin_date = get_next_occurrence_from_day_month(
                        datetime.strptime(
                            bin_date_info[0],
                            "%A %d %B -",
                        )
                    )
                # On exceptional collection schedule (e.g. around English Bank Holidays), date will be contained in the second stripped string
                else:
                    bin_date = get_next_occurrence_from_day_month(
                        datetime.strptime(
                            bin_date_info[1],
                            "%A %d %B -",
                        )
                    )
            except Exception as ex:
                raise ValueError(f"Error parsing bin data: {ex}")

            if (datetime.now().month == 12) and (bin_date.month == 1):
                bin_date = bin_date.replace(year=next_year)
            else:
                bin_date = bin_date.replace(year=current_year)

            # Build data dict for each entry
            dict_data = {
                "type": bin_type,
                "collectionDate": bin_date.strftime(date_format),
            }
            data["bins"].append(dict_data)

        data["bins"].sort(
            key=lambda x: datetime.strptime(x.get("collectionDate"), date_format)
        )

        return data


# --- Adapter for Project API ---
from api.compat.hacs import Collection  # type: ignore[attr-defined]

TITLE = "Vale of White Horse"
URL = "https://eform.whitehorsedc.gov.uk/ebase/BINZONE_DESKTOP.eb"
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
