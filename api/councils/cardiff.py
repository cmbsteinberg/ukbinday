"""Cardiff: obtain a JWT with SOAP, then request waste collections by UPRN."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from datetime import datetime

from api.councils._base import (
    Address,
    Collection,
    Http,
    Meta,
    Scraper,
    UpstreamError,
)

_URL_COLLECTIONS = "https://api.cardiff.gov.uk/WasteManagement/api/WasteCollection"
_URL_GET_JWT = "https://authwebservice.cardiff.gov.uk/AuthenticationWebService.asmx?op=GetJWT"
_PAYLOAD_GET_JWT = (
    "<?xml version='1.0' encoding='utf-8'?>"
    "<soap:Envelope xmlns:xsi='http://www.w3.org/2001/XMLSchema-instance'"
    " xmlns:xsd='http://www.w3.org/2001/XMLSchema'"
    " xmlns:soap='http://schemas.xmlsoap.org/soap/envelope/'>"
    "<soap:Body>"
    "<GetJWT xmlns='http://tempuri.org/' />"
    "</soap:Body>"
    "</soap:Envelope>"
)


async def _get_token(http: Http) -> str:
    response = await http.post(
        _URL_GET_JWT,
        content=_PAYLOAD_GET_JWT,
        headers={"Content-Type": 'text/xml; charset="UTF-8"'},
    )
    try:
        tree = ET.fromstring(response.text)
    except ET.ParseError as exc:
        raise UpstreamError("Cardiff's authentication response was not valid XML") from exc

    result = tree.find(".//GetJWTResult", namespaces={"": "http://tempuri.org/"})
    if result is None or result.text is None:
        raise UpstreamError("Cardiff's authentication response did not contain a token")
    try:
        return json.loads(result.text)["access_token"]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise UpstreamError("Cardiff's authentication response did not contain a valid token") from exc


class Cardiff(Scraper):
    meta = Meta(
        title="Cardiff Council",
        url="https://cardiff.gov.uk",
        lads=("W06000015",),
        cases={
            "Glass": {"uprn": "100100124569"},
            "NoGlass": {"uprn": "100100127440"},
        },
    )
    requires = frozenset({"uprn"})
    headers = {
        "Origin": "https://www.cardiff.gov.uk",
        "Referer": "https://www.cardiff.gov.uk/",
        "User-Agent": "Mozilla/5.0",
    }

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        payload = {
            "systemReference": "web",
            "language": "eng",
            "uprn": address.need("uprn"),
        }
        token = await _get_token(http)
        response = await http.post(
            _URL_COLLECTIONS,
            headers={"Authorization": f"Bearer {token}"},
            json=payload,
        )

        collections = response.json()
        entries = []
        for week in collections["collectionWeeks"]:
            for bin_data in week["bins"]:
                entries.append(
                    Collection(
                        date=datetime.fromisoformat(week["date"]).date(),
                        type=bin_data["type"],
                    )
                )
        return entries


SCRAPER = Cardiff()
