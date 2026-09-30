from bs4 import BeautifulSoup
from api.compat.ukbcd.common import *
from api.compat.ukbcd.get_bin_data import AbstractGetBinDataClass
from api.compat import httpx_helpers as _http


class CouncilClass(AbstractGetBinDataClass):
    """
    Concrete classes have to implement all abstract operations of the
    base class. They can also override some operations with a default
    implementation.
    """

    UPRN_LOOKUP_URL = "https://swict.malvernhills.gov.uk/sw2AddressLookupWS/jaxrs/PostCode"

    async def parse_data(self, page: str, **kwargs) -> dict:
        api_url = "https://swict.malvernhills.gov.uk/mhdcroundlookup/HandleSearchScreen"

        user_uprn = kwargs.get("uprn")
        user_postcode = kwargs.get("postcode")
        user_paon = kwargs.get("paon")

        if not user_uprn and user_postcode:
            user_uprn = await self._resolve_uprn(user_postcode, user_paon)

        check_uprn(user_uprn)

        form_data = {"nmalAddrtxt": "", "alAddrsel": user_uprn}

        pass  # urllib3 warnings disabled
        response = await _http.post(api_url, data=form_data)

        soup = BeautifulSoup(response.text, features="html.parser")
        soup.prettify()

        table_element = soup.find("table")
        if not table_element:
            raise ValueError(
                "No results table found — UPRN may be invalid or address not in bin round records"
            )

        table_body = table_element.find("tbody")
        rows = table_body.find_all("tr")

        data = {"bins": []}

        for row in rows:
            columns = row.find_all("td")
            columns = [ele.text.strip() for ele in columns]

            thisCollection = [ele for ele in columns if ele]

            if "Not applicable" not in thisCollection[1]:
                bin_type = thisCollection[0].replace("collection", "").strip()
                date = datetime.strptime(thisCollection[1], "%A %d/%m/%Y")
                dict_data = {
                    "type": bin_type,
                    "collectionDate": date.strftime(date_format),
                }
                data["bins"].append(dict_data)

        return data

    async def _resolve_uprn(self, postcode: str, house_number: str = None) -> str:
        params = {
            "simple": "T",
            "pcode": postcode,
            "authority": "MHDC",
            "historical": "false",
            "hidedummyuprn": "1",
        }
        response = await _http.get(self.UPRN_LOOKUP_URL, params=params)
        response.raise_for_status()
        results = response.json().get("jArray", [])

        if not results:
            raise ValueError(f"No addresses found for postcode {postcode}")

        if house_number:
            house_lower = house_number.lower().strip()
            for entry in results:
                addr = entry.get("Address_Short", "").lower()
                addr_parts = addr.split()
                if addr_parts and addr_parts[0] == house_lower:
                    return entry["UPRN"]
            # Fallback: check if house_number appears at start followed by separator
            for entry in results:
                addr = entry.get("Address_Short", "").lower()
                if addr.startswith(house_lower + " ") or addr.startswith(house_lower + ","):
                    return entry["UPRN"]

        if len(results) == 1:
            return results[0]["UPRN"]

        raise ValueError(
            f"Multiple addresses found for {postcode} — provide house_number to disambiguate"
        )


# --- Adapter for Project API ---
from api.compat.hacs import Collection  # type: ignore[attr-defined]

TITLE = "Malvern Hills"
URL = "https://swict.malvernhills.gov.uk/mhdcroundlookup/HandleSearchScreen"
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
