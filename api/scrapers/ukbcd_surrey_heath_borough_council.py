import urllib

from bs4 import BeautifulSoup

from api.compat.ukbcd.common import *
from api.compat.ukbcd.get_bin_data import AbstractGetBinDataClass
import httpx


class CouncilClass(AbstractGetBinDataClass):
    """
    Concrete classes have to implement all abstract operations of the
    base class. They can also override some operations with a default
    implementation.
    """

    def parse_data(self, page: str, **kwargs) -> dict:
        pass  # urllib3 warnings disabled
        root_url = "https://asjwsw-wrpsurreyheathmunicipal-live.whitespacews.com/"
        # Get the house number and postcode from the commandline
        user_paon = kwargs.get("paon")
        user_postcode = kwargs.get("postcode")
        check_postcode(user_postcode)

        # Start a new session for the form, and get the chosen URL from the commandline
        session = httpx.Client(follow_redirects=True)
        req = session.get(root_url)

        # Parse the requested URL to get a link to the "View My Collections" portal with a unique service ID
        start = BeautifulSoup(req.text, features="html.parser")
        start.prettify()
        base_link = start.select(
            "#menu-content > div > div:nth-child(1) > p.govuk-body.govuk-\\!-margin-bottom-0.colorblue.lineheight15 > a"
        )[0].attrs.get("href")

        # We need to reorder the query parts from the unique URL, so split them up to make it easier
        query_parts = urllib.parse.urlparse(base_link).query.split("&")
        parts = base_link.split("?")
        addr_link = (
            parts[0] + "/mop.php?" + query_parts[1] + "&" + query_parts[0] + "&seq=2"
        )

        # Bring in some headers to emulate a browser, and put the UPRN and postcode into the form data.
        # This is sent in a POST request, emulating browser behaviour.
        headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
            "Accept-Language": "en-GB,en;q=0.9",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Content-Type": "application/x-www-form-urlencoded",
            "Origin": "https://asjwsw-wrpsurreyheathmunicipal-live.whitespacews.com",
            "Pragma": "no-cache",
            "Referer": "https://asjwsw-wrpsurreyheathmunicipal-live.whitespacews.com/",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-User": "?1",
            "Upgrade-Insecure-Requests": "1",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36 OPR/98.0.0.0",
            "sec-ch-ua": '"Chromium";v="112", "Not_A Brand";v="24", "Opera GX";v="98"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
        }
        data = {
            "address_name_number": user_paon,
            "address_street": "",
            "street_town": "",
            "address_postcode": user_postcode,
        }
        addr_page = session.post(addr_link, headers=headers, data=data)
        addr = BeautifulSoup(addr_page.text, features="html.parser")
        addr.prettify()

        # This page should only have one address, but regardless, select the first one and make a request to load the
        # calendar page.
        cal_link = root_url + addr.select("#property_list > ul > li > a")[0].attrs.get(
            "href"
        )
        cal_page = session.get(cal_link)

        # Parse the calendar page
        soup = BeautifulSoup(cal_page.text, features="html.parser")
        soup.prettify()
        data = {"bins": []}

        # For whatever reason, each row contains all the information for that row, and each one after it. This code
        # essentially gets all items from each row, but ignores the whitespace that you get when splitting using \n.
        # This produces a big list of dates then bin types, so we split them up into a list of lists - each pair is
        # a date and the bin type.
        items = [
            i
            for i in soup.find(
                "u1",
                {
                    "class": "displayinlineblock justifycontentleft alignitemscenter margin0 padding0"
                },
            ).text.split("\n")
            if i != ""
        ]
        pairs = [items[i : i + 2] for i in range(0, len(items), 2)]

        # Loop through the paired bin dates and types
        for pair in pairs:
            # This isn't necessary, but better safe than sorry
            collection_date = datetime.strptime(pair[0], date_format).strftime(
                date_format
            )
            # Change the formatting of the purple bins to replace the hyphens with slashes
            if pair[1] == "Batteries-small electricals-textiles":
                bin_type = pair[1].replace("-", "/").strip()
            else:
                bin_type = pair[1]

            # Add the data into the dictionary
            data["bins"].append({"type": bin_type, "collectionDate": collection_date})

        return data


# --- Adapter for Project API ---
from api.compat.hacs import Collection  # type: ignore[attr-defined]

TITLE = "Surrey Heath"
URL = "https://asjwsw-wrpsurreyheathmunicipal-live.whitespacews.com/"
TEST_CASES = {}


class Source:
    def __init__(self, postcode: str | None = None, house_number: str | None = None):
        self.postcode = postcode
        self.house_number = house_number
        self._scraper = CouncilClass()

    async def fetch(self) -> list[Collection]:
        import asyncio
        from datetime import datetime

        kwargs = {}
        if self.postcode: kwargs['postcode'] = self.postcode
        if self.house_number: kwargs['paon'] = self.house_number

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
