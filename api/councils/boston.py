"""Boston: submit the postcode and property number to its GOSS waste form, then select the returned UPRN."""

from __future__ import annotations

import base64
import json
import re
from datetime import datetime
from typing import Any

from api.councils._base import (
    Address,
    AddressNotFound,
    Collection,
    Http,
    Meta,
    Scraper,
    UpstreamError,
    match_address,
)

_FORM_URL = "https://www.boston.gov.uk/article/27449/Your-Waste-Collections"
_FORM_NAME = "BBCWASTECOLLECTIONSV2"
_SUBMISSION_URL = "https://www.boston.gov.uk/apiserver/formsservice/http/processsubmission"


def _decode_sv(text: str) -> dict[str, Any]:
    """Decode the serialized variables from the GOSS form page."""
    match = re.search(rf"var {_FORM_NAME}SerializedVariables = \"([^\"]+)\"", text)
    if not match:
        return {}
    return json.loads(base64.b64decode(match.group(1)))


def _get_form_params(text: str) -> dict[str, str]:
    """Extract the GOSS form session parameters from a page."""
    nonce = re.search(rf'"{_FORM_NAME}_NONCE" value="([\w-]+)"', text)
    sessionid = re.search(rf'"{_FORM_NAME}_SESSIONID" value="([\w-]+)"', text)
    pagesessionid = re.search(rf'"{_FORM_NAME}_PAGESESSIONID" value="([\w-]+)"', text)
    return {
        "nonce": nonce.group(1) if nonce else "",
        "sessionid": sessionid.group(1) if sessionid else "",
        "pagesessionid": pagesessionid.group(1) if pagesessionid else "",
    }


def _get_url_params(url: str) -> dict[str, str]:
    """Extract pageSessionId and fsn from a URL."""
    psi = re.search(r"pageSessionId=([\w-]+)", url)
    fsn = re.search(r"fsn=([\w-]+)", url)
    return {
        "pagesessionid_url": psi.group(1) if psi else "",
        "fsn_url": fsn.group(1) if fsn else "",
    }


class Boston(Scraper):
    meta = Meta(
        title="Boston Borough Council",
        url=_FORM_URL,
        lads=("E07000136",),
        cases={
            "43 Tarry Hill, Swineshead, PE20 3LW": {
                "postcode": "PE20 3LW",
                "house_number": "43",
            },
            "The Old Vicarage, Church Close, PE21 6NE": {
                "postcode": "PE21 6NE",
                "house_number": "10",
            },
        },
    )
    requires = frozenset({"postcode"})
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        postcode = address.need("postcode")
        property_number = address.house_number or ""

        # Step 1: Load initial form page to get session tokens.
        r1 = await http.get(_FORM_URL, timeout=30)
        url_params1 = _get_url_params(r1.url)
        form_params1 = _get_form_params(r1.text)
        psi1 = re.search(r"pageSessionId=([\w-]+)", r1.text)

        submission_url1 = (
            f"{_SUBMISSION_URL}"
            f"?pageSessionId={psi1.group(1) if psi1 else url_params1['pagesessionid_url']}"
            f"&fsid={form_params1['sessionid']}"
            f"&fsn={form_params1['nonce']}"
        )

        # Step 2: Submit search form with postcode and property number.
        data2 = {
            f"{_FORM_NAME}_PAGESESSIONID": form_params1["pagesessionid"],
            f"{_FORM_NAME}_SESSIONID": form_params1["sessionid"],
            f"{_FORM_NAME}_NONCE": form_params1["nonce"],
            f"{_FORM_NAME}_VARIABLES": "",
            f"{_FORM_NAME}_PAGENAME": "COLLECTIONS",
            f"{_FORM_NAME}_PAGEINSTANCE": "0",
            f"{_FORM_NAME}_COLLECTIONS_SEARCHPROPERTYNAMENUMBER": property_number,
            f"{_FORM_NAME}_COLLECTIONS_SEARCHPOSTCODE": postcode,
            f"{_FORM_NAME}_FORMACTION_NEXT": f"{_FORM_NAME}_COLLECTIONS_START10",
        }

        r2 = await http.post(
            submission_url1,
            data=data2,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=30,
        )

        sv2 = _decode_sv(r2.text)
        addr_options = sv2.get("ADDRESSUPRN_OPTIONDATA", {}).get("value", [])

        # Filter out placeholder entries (empty UPRN / "Select address").
        valid_options = [
            option
            for option in addr_options
            if option[0] and str(option[0]).strip() and option[1] != "Select address"
        ]

        if not valid_options:
            raise AddressNotFound(
                f"No addresses found for postcode '{postcode}' "
                f"and property '{property_number}'. "
                "Please check your postcode and property name/number."
            )

        selected_option = match_address(
            address,
            valid_options,
            text=lambda option: str(option[1]),
            uprn=lambda option: option[0],
        )
        uprn = selected_option[0]

        url_params2 = _get_url_params(r2.url)
        form_params2 = _get_form_params(r2.text)

        submission_url2 = (
            f"{_SUBMISSION_URL}"
            f"?pageSessionId={url_params2['pagesessionid_url']}"
            f"&fsid={form_params2['sessionid']}"
            f"&fsn={url_params2['fsn_url']}"
        )

        # Step 3: Select address by UPRN to get collection data.
        data3 = {
            f"{_FORM_NAME}_PAGESESSIONID": form_params2["pagesessionid"],
            f"{_FORM_NAME}_SESSIONID": form_params2["sessionid"],
            f"{_FORM_NAME}_NONCE": form_params2["nonce"],
            f"{_FORM_NAME}_VARIABLES": "",
            f"{_FORM_NAME}_PAGENAME": "ADDRESS",
            f"{_FORM_NAME}_PAGEINSTANCE": "0",
            f"{_FORM_NAME}_ADDRESS_FIELD1034": "false",
            f"{_FORM_NAME}_ADDRESS_FIELD1036": "false",
            f"{_FORM_NAME}_ADDRESS_FIELD1041": "true",
            f"{_FORM_NAME}_ADDRESS_FIELD1042": "false",
            f"{_FORM_NAME}_ADDRESS_ADDRESSUPRN": str(uprn),
            f"{_FORM_NAME}_FORMACTION_NEXT": f"{_FORM_NAME}_ADDRESS_NEXT3",
        }

        r3 = await http.post(
            submission_url2,
            data=data3,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=30,
        )

        sv3 = _decode_sv(r3.text)
        collections_data = sv3.get("collectionsData", {}).get("value", {})

        if not collections_data.get("success"):
            raise UpstreamError(
                f"Failed to retrieve collection data for UPRN {uprn}. "
                "The council website may be temporarily unavailable."
            )

        collections = []
        for job in collections_data.get("jobs", []):
            next_date_str = job.get("NextDate")
            if not next_date_str:
                continue
            try:
                next_date = datetime.strptime(next_date_str, "%Y-%m-%d").date()
            except ValueError:
                continue

            bin_type = job.get("Type", "").lower()
            title = job.get("Title", bin_type)
            collections.append(Collection(date=next_date, type=title))

        return collections


SCRAPER = Boston()
