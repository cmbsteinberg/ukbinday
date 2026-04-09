from datetime import datetime

import httpx
from bs4 import BeautifulSoup

from api.compat.ukbcd.common import date_format
from api.compat.ukbcd.get_bin_data import AbstractGetBinDataClass


BIN_TYPES = (
    "Domestic Waste",
    "Garden Waste",
    "Recycling",
    "Food Waste",
)

SUFFIXES = (
    " Collection Service",
    " Collection - refer to calendar for stream",
)


class CouncilClass(AbstractGetBinDataClass):
    """
    Concrete classes have to implement all abstract operations of the
    base class. They can also override some operations with a default
    implementation.
    """

    def parse_data(self, page: str, **kwargs) -> dict:
        # data to return
        data = {"bins": []}

        # start session
        # note: this ignores the given url
        base_url = "https://lcc-wrp.whitespacews.com"
        session = httpx.Client(follow_redirects=True)
        response = session.get(base_url + "/#!")
        links = [
            a["href"]
            for a in BeautifulSoup(response.text, features="html.parser").select("a")
        ]
        portal_link = ""
        for l in links:
            if "seq=1" in l:
                portal_link = l

        # fill address form
        response = session.get(portal_link)
        form = BeautifulSoup(response.text, features="html.parser").find("form")
        form_url = dict(form.attrs).get("action")
        payload = {
            "address_name_number": kwargs.get("number"),
            "address_street": "",
            "address_postcode": kwargs.get("postcode"),
        }

        # get (first) found address
        response = session.post(form_url, data=payload)
        links = [
            a["href"]
            for a in BeautifulSoup(response.text, features="html.parser").select("a")
        ]
        addr_link = ""
        for l in links:
            if "seq=3" in l:
                addr_link = base_url + "/" + l

        # get json formatted bin data for addr
        response = session.get(addr_link)
        new_soup = BeautifulSoup(response.text, features="html.parser")
        services = new_soup.find("section", {"id": "scheduled-collections"})

        if services is None:
            raise Exception("Could not find scheduled collections section on the page")

        services_sub = services.find_all("li")
        if not services_sub:
            raise Exception("No collection services found")

        for i in range(0, len(services_sub), 3):
            if i + 2 < len(services_sub):
                date_item = services_sub[i + 1]
                type_item = services_sub[i + 2]
                if date_item is None:
                    raise Exception(f"Missing collection date element at index {i + 1}")
                if type_item is None:
                    raise Exception(f"Missing collection type element at index {i + 2}")

                date_text = date_item.text.strip()
                type_text = type_item.text.strip()

                try:
                    dt = datetime.strptime(date_text, "%d/%m/%Y").date()
                except ValueError as exc:
                    raise ValueError(
                        "Unexpected Lancaster schedule date format: "
                        f"date_text='{date_text}', type_text='{type_text}'"
                    ) from exc

                collection_type = next(
                    (
                        bin_type
                        for bin_type in BIN_TYPES
                        if type_text.startswith(bin_type)
                    ),
                    None,
                )
                if collection_type is None:
                    collection_type = type_text
                    for suffix in SUFFIXES:
                        collection_type = collection_type.removesuffix(suffix)
                if collection_type is not None:
                    data["bins"].append(
                        {
                            "type": collection_type,
                            "collectionDate": dt.strftime(date_format),
                        }
                    )

        data["bins"].sort(
            key=lambda x: datetime.strptime(x.get("collectionDate"), date_format)
        )

        return data


# --- Adapter for Project API ---
from api.compat.hacs import Collection  # type: ignore[attr-defined]

TITLE = "Lancaster"
URL = "https://lcc-wrp.whitespacews.com"
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
