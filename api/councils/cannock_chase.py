"""Cannock Chase: submit a padded UPRN and postcode to the collections XML API."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import datetime

from api.councils._base import (
    Address,
    Collection,
    Http,
    InputError,
    Meta,
    Scraper,
    UpstreamError,
)

_API_URL = "https://ccdc.opendata.onl/DynamicCall.dll"
_NAMESPACE = {"ws": "http://webservices.whitespacews.com/"}
_SERVICE_NAME_MAP = {
    "Refuse Collection Service": "Refuse",
    "Recycle Collection Service": "Recycling",
    "Garden Collection Service": "Garden waste",
    "Food Waste Collection Service": "Food waste",
}


class CannockChase(Scraper):
    meta = Meta(
        title="Cannock Chase Council",
        url="https://www.cannockchasedc.gov.uk",
        lads=("E07000192",),
        cases={
            "Test_001": {"uprn": "100031640287", "postcode": "WS15 1DN"},
            "Test_002": {"uprn": "100031640289", "postcode": "WS15 1DN"},
            "Test_003": {"uprn": "100031624295", "postcode": "WS11 6DY"},
        },
    )
    requires = frozenset({"uprn", "postcode"})

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        r = await http.post(
            _API_URL,
            data={
                "Method": "CollectionDates",
                "UPRN": address.need("uprn").zfill(12),
                "Postcode": address.need("postcode"),
            },
        )

        try:
            tree = ET.fromstring(r.text)
        except ET.ParseError as exc:
            raise UpstreamError("Cannock Chase returned invalid XML") from exc

        success_flag_element = tree.find(".//ws:SuccessFlag", _NAMESPACE)
        if success_flag_element is not None and success_flag_element.text != "true":
            error_code_element = tree.find(".//ws:ErrorCode", _NAMESPACE)
            error_description_element = tree.find(".//ws:ErrorDescription", _NAMESPACE)

            if error_code_element is not None and error_code_element.text == "6":
                raise InputError("UPRN is invalid or outside the Cannock Chase Council area")

            if error_description_element is not None and error_description_element.text is not None:
                raise UpstreamError(f"API returned error: {error_description_element.text}")
            raise UpstreamError("API returned error")

        collections = []
        for collection in tree.findall(".//ws:Collection", _NAMESPACE):
            date_element = collection.find("ws:Date", _NAMESPACE)
            service_element = collection.find("ws:Service", _NAMESPACE)

            if (
                date_element is None
                or date_element.text is None
                or service_element is None
                or service_element.text is None
            ):
                continue

            service_name = _SERVICE_NAME_MAP.get(service_element.text, service_element.text)
            collections.append(
                Collection(
                    datetime.strptime(date_element.text, "%d/%m/%Y %H:%M:%S").date(),
                    service_name,
                )
            )

        return collections


SCRAPER = CannockChase()
