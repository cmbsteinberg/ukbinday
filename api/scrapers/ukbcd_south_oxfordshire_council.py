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

    async def parse_data(self, page: str, **kwargs) -> dict:
        user_uprn = kwargs.get("uprn")
        check_uprn(user_uprn)

        # UPRN is passed in via a cookie. Set cookies/params and GET the page
        headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
            "Accept-Language": "en-GB,en;q=0.7",
            "Cache-Control": "max-age=0",
            "Connection": "keep-alive",
            "Referer": "https://eform.southoxon.gov.uk/ebase/BINZONE_DESKTOP.eb?SOVA_TAG=SOUTH&ebd=0&ebz=1_1668467255368",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-User": "?1",
            "Sec-GPC": "1",
            "Upgrade-Insecure-Requests": "1",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36",
        }
        params = {
            "SOVA_TAG": "SOUTH",
            "ebd": "0",
            # 'ebz':      '1_1668467255368',
        }
        pass  # urllib3 warnings disabled
        # Azure App Gateway intermittently returns 403 on direct requests.
        # Establishing a JSESSIONID by visiting the page first (without the
        # SVBINZONE cookie) avoids this.
        session = httpx.AsyncClient(verify=False, follow_redirects=True)
        session.headers.update(headers)
        await session.get(
            "https://eform.southoxon.gov.uk/ebase/BINZONE_DESKTOP.eb?SOVA_TAG=SOUTH&ebd=0&ebz=1_1668467255368",
            
            timeout=15,
        )
        session.cookies.set("SVBINZONE", f"SOUTH%3AUPRN%40{user_uprn}")
        response = await session.get(
            "https://eform.southoxon.gov.uk/ebase/BINZONE_DESKTOP.eb",
            params=params,
            headers=headers,
            
            timeout=15,
        )

        # Parse response text for super speedy finding
        soup = BeautifulSoup(response.text, features="html.parser")
        soup.prettify()

        data = {"bins": []}

        today = datetime.now().date()

        # Page has slider info side by side, which are two instances of this class
        for bin in soup.find_all("div", {"class": "binextra"}):
            bin_info = list(bin.stripped_strings)
            try:
                # On standard collection schedule, date will be contained in the first stripped string
                if contains_date(bin_info[0]):
                    raw_date = bin_info[0]
                    type_start = 1
                # On exceptional collection schedule (e.g. around English Bank Holidays), date will be contained in the second stripped string
                else:
                    raw_date = bin_info[1]
                    type_start = 2

                bin_date = datetime.strptime(
                    f"{raw_date} {today.year}", "%A %d %B - %Y"
                ).date()

                # Strip supplementary notes (e.g. "Don't forget...", "Extra garden waste...")
                # that follow the bin-type description.
                type_parts = []
                for part in bin_info[type_start:]:
                    if "don't" in part.lower() or part.startswith("Extra"):
                        break
                    type_parts.append(part)
                combined_type = " ".join(type_parts)
            except Exception:
                continue

            # This is a fortnightly rota, published as the current fortnight's
            # combined collection rather than the next occurrence, so a date
            # earlier in the same fortnight parses to the past - roll it
            # forward (day-based, so it naturally crosses a year boundary).
            while bin_date < today:
                bin_date += timedelta(days=14)

            # The council describes each visit as one combined sentence (e.g.
            # "Grey bin, small electrical items and food bin") covering
            # everything collected that day - split it into its individual
            # bins rather than one long, uncolour-mappable type string.
            for bin_type in combined_type.replace(" and ", ", ").split(","):
                bin_type = bin_type.strip().capitalize()
                if not bin_type:
                    continue
                data["bins"].append(
                    {
                        "type": bin_type,
                        "collectionDate": bin_date.strftime(date_format),
                    }
                )

        data["bins"].sort(
            key=lambda x: datetime.strptime(x.get("collectionDate"), date_format)
        )

        return data


# --- Adapter for Project API ---
from api.compat.hacs import Collection  # type: ignore[attr-defined]

TITLE = "South Oxfordshire"
URL = "https://www.southoxon.gov.uk/south-oxfordshire-district-council/recycling-rubbish-and-waste/when-is-your-collection-day/"
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
