# So this script is a little different to the others...
# Essentially, it uses Cardiff Council's waste collection API to return collections for a UPRN by pretending
# to be Google Chrome

import datetime
import json
from datetime import datetime

import httpx
import httpx
from api.compat.ukbcd.common import *
from api.compat.ukbcd.get_bin_data import AbstractGetBinDataClass


# Taken from
# https://stackoverflow.com/questions/29931671/making-an-api-call-in-python-with-an-api-that-requires-a-bearer-token
class BearerAuth(object):
    def __init__(self, token):
        self.token = token

    def __call__(self, r):
        r.headers["authorization"] = "Bearer " + self.token
        return r


def parse_token(text: str) -> str:
    """
    Parses the response text to find the JWT token, which will always be the longest item in the list (I think)
        :param text: The response text from the server
        :return: Only the JWT token, as a string
    """
    # You'd have thought I'd use something like etree for this, but that doesn't work so going for a hacky approach
    xml_list = text.split('"')
    bearer_token = max(xml_list, key=len)
    return bearer_token


def get_jwt() -> str:
    """
    Gets a JSON web token from the authentication server
        :return: A JWT token as a string
    """
    auth_url = (
        "https://authwebservice.cardiff.gov.uk/AuthenticationWebService.asmx?op=GetJWT"
    )
    options_headers_str = (
        "Accept: */*|Accept-Encoding: gzip, "
        "deflate, br|Accept-Language: en-GB,en;q=0.9|Access-Control-Request-Headers: content-type"
        "|Access-Control-Request-Method: POST|Connection: keep-alive|Host: "
        "authwebservice.cardiff.gov.uk|Origin: https://www.cardiff.gov.uk|Referer: "
        "https://www.cardiff.gov.uk/|Sec-Fetch-Dest: empty"
        "|Sec-Fetch-Mode: cors|Sec-Fetch-Site: same-site|User-Agent: Mozilla/5.0 (Windows NT 10.0; "
        "Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36 "
    )

    request_headers_str = (
        "Accept: */*|Accept-Encoding: gzip, deflate, br|Accept-Language: en-GB,en;q=0.9|Connection: "
        'keep-alive|Content-Length: 284|Content-Type: text/xml; charset="UTF-8"|Host: '
        "authwebservice.cardiff.gov.uk|Origin: https://www.cardiff.gov.uk|Referer: "
        "https://www.cardiff.gov.uk/|Sec-Fetch-Dest: empty|Sec-Fetch-Mode: cors|Sec-Fetch-Site: "
        "same-site|Sec-GPC: 1|User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36 "
    )

    payload = (
        "<?xml version='1.0' encoding='utf-8'?><soap:Envelope "
        "xmlns:xsi='http://www.w3.org/2001/XMLSchema-instance' xmlns:xsd='http://www.w3.org/2001/XMLSchema' "
        "xmlns:soap='http://schemas.xmlsoap.org/soap/envelope/'><soap:Body><GetJWT xmlns='http://tempuri.org/' "
        "/></soap:Body></soap:Envelope> "
    )

    options_headers = parse_header(options_headers_str)
    request_headers = parse_header(request_headers_str)
    try:
        pass  # urllib3 warnings disabled
        options = httpx.options(auth_url, headers=options_headers)
        response = httpx.post(auth_url, headers=request_headers, data=payload)
        if not options.is_success or not response.is_success:
            raise ValueError("Invalid server response code getting JWT!")

    except Exception as ex:
        print(f"Exception encountered: {ex}")
        exit(1)
    token = parse_token(response.text)
    options.close()
    response.close()

    return token


class CouncilClass(AbstractGetBinDataClass):
    """
    Concrete classes have to implement all abstract operations of the base
    class. They can also override some operations with a default
    implementation.
    """

    def parse_data(self, page: str, **kwargs) -> dict:
        """
        Parse council provided CSVs to get the latest bin collections for address
        """
        # Change this
        uprn = kwargs.get("uprn")
        check_uprn(uprn)

        data = {"bins": []}
        token = get_jwt()

        api_url = "https://api.cardiff.gov.uk/WasteManagement/api/WasteCollection"
        options_header_str = (
            "Accept: */*|Accept-Encoding: gzip, deflate, br|Accept-Language: en-GB,"
            "en;q=0.9|Access-Control-Request-Headers: authorization,"
            "content-type|Access-Control-Request-Method: POST|Connection: keep-alive|Host: "
            "api.cardiff.gov.uk|Origin: https://www.cardiff.gov.uk|Referer: "
            "https://www.cardiff.gov.uk/|Sec-Fetch-Dest: empty|Sec-Fetch-Mode: cors|Sec-Fetch-Site: "
            "same-site|User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 ("
            "KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36 "
        )
        response_header_str = (
            "Accept: application/json, text/javascript, */*; q=0.01|Accept-Encoding: gzip, deflate, "
            f"br|Accept-Language: en-GB,en;q=0.9|Authorization: {token}|Connection: "
            "keep-alive|Content-Length: 62|Content-Type: application/json; charset=UTF-8|Host: "
            "api.cardiff.gov.uk|Origin: https://www.cardiff.gov.uk|Referer: "
            "https://www.cardiff.gov.uk/|Sec-Fetch-Dest: empty|Sec-Fetch-Mode: cors|Sec-Fetch-Site: "
            "same-site|Sec-GPC: 1|User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36 "
        )

        payload = (
            '{ "systemReference": "web", "language": "eng", ' f'"uprn": {uprn} ' "}"
        )

        options_header = parse_header(options_header_str)
        response_header = parse_header(response_header_str)
        # Copy the request headers for options and post headers (replacing post auth with token variable) and post
        # payload, then add here
        try:
            pass  # urllib3 warnings disabled
            options = httpx.options(api_url, headers=options_header)
            response = httpx.post(
                api_url, headers=response_header, auth=BearerAuth(token), data=payload
            )
            if not options.is_success or not response.is_success:
                raise ValueError("Invalid server response code finding UPRN!")

        except Exception as ex:
            print(f"Exception encountered: {ex}")
            exit(1)

        result = json.loads(response.text)

        options.close()
        response.close()

        collections = result["collectionWeeks"]
        for week in collections:
            collection = [(k, v) for k, v in week.items()]
            collection_date = collection[1][1]
            collection_date = datetime.strptime(
                collection_date, "%Y-%m-%dT%H:%M:%S"
            ).strftime(date_format)

            for bin in collection[3][1]:
                bin_type = bin.get("type")

                dict_data = {
                    "type": bin_type,
                    "collectionDate": collection_date,
                }
                data["bins"].append(dict_data)

        return data


# --- Adapter for Project API ---
from api.compat.hacs import Collection  # type: ignore[attr-defined]

TITLE = "Cardiff"
URL = "https://www.gov.uk"
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
