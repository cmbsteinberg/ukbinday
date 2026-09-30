"""Tandridge: search LLPG records by postcode, then request the selected property's collections."""

from __future__ import annotations

from datetime import datetime
from xml.etree import ElementTree as ET

from api.councils._base import (
    Address,
    Collection,
    Http,
    Meta,
    Scraper,
    UpstreamError,
    match_address,
)

_SEARCH_URL = (
    "https://tdcws01.tandridge.gov.uk/TDCWebAppsPublic/WebServices/"
    "wsLLPGSearch2018/LLPGQuery_v2_3.asmx?op=SearchByAllAddressDetails"
)
_COLLECTIONS_URL = (
    "https://tdcws01.tandridge.gov.uk/TDCWebAppsPublic/TDCMiddleware/"
    "RESTAPI/WhiteSpaceAPI/GetCompleteRecordByUPRN"
)

_NS = {
    "soap": "http://www.w3.org/2003/05/soap-envelope",
    "tdc": "http://www.tandridge.gov.uk/Webservices/",
}

_SEARCH_XML_TEMPLATE = """<?xml version="1.0" encoding="utf-8"?>
<soap12:Envelope xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:xsd="http://www.w3.org/2001/XMLSchema" xmlns:soap12="http://www.w3.org/2003/05/soap-envelope">
  <soap12:Body>
    <SearchByAllAddressDetails xmlns="http://www.tandridge.gov.uk/Webservices/">
      <SearchAddress></SearchAddress>
      <SearchTownName></SearchTownName>
      <SearchLocalityName></SearchLocalityName>
      <SearchPostCode>{postcode}</SearchPostCode>
      <SearchReference></SearchReference>
      <SearchXPos></SearchXPos>
      <SearchYPos></SearchYPos>
      <SearchDistance></SearchDistance>
      <ReturnMaxRecords></ReturnMaxRecords>
      <MustHaveRefType></MustHaveRefType>
      <ShowXrefTypes></ShowXrefTypes>
      <sUseDate></sUseDate>
      <sSearchAlternatives>1,3,6</sSearchAlternatives>
      <sPrimaryClassifications></sPrimaryClassifications>
      <sSecondaryClassifications></sSecondaryClassifications>
      <sTertiaryClassifications></sTertiaryClassifications>
      <ShowNonAddressable></ShowNonAddressable>
      <AllowSearchOrganisations></AllowSearchOrganisations>
    </SearchByAllAddressDetails>
  </soap12:Body>
</soap12:Envelope>"""

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
}


class Tandridge(Scraper):
    meta = Meta(
        title="Tandridge District Council",
        url="https://www.tandridge.gov.uk",
        lads=("E07000215",),
        cases={
            "14A Station Road East, Oxted": {
                "postcode": "RH8 0PG",
                "house_number": "14A",
            },
            "22A Station Road East, Oxted": {
                "postcode": "RH8 0PG",
                "house_number": "22A",
            },
            "No postcode space": {
                "postcode": "RH80PG",
                "house_number": "16A",
            },
        },
    )
    requires = frozenset({"postcode", "house_number"})
    headers = _HEADERS

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        xml_request = _SEARCH_XML_TEMPLATE.format(postcode=address.need("postcode"))
        r = await http.post(
            _SEARCH_URL,
            content=xml_request.encode("utf-8"),
            headers={"Content-Type": "text/xml; charset=utf-8"},
        )

        try:
            root = ET.fromstring(r.text)
        except ET.ParseError as exc:
            raise UpstreamError("Tandridge returned an invalid address search response") from exc

        records = root.findall(".//tdc:LLPGRecord", _NS)
        candidates: list[tuple[str, str]] = []
        for record in records:
            house_part = record.findtext("tdc:BS7666Format/tdc:HousePart", namespaces=_NS)
            uprn = record.findtext("tdc:BS7666Format/tdc:UPRN", namespaces=_NS)
            if not uprn or not house_part:
                continue
            candidates.append((house_part.strip(), uprn))

        selected = match_address(
            address,
            candidates,
            text=lambda candidate: candidate[0],
            uprn=lambda candidate: candidate[1],
        )

        r = await http.post(
            _COLLECTIONS_URL,
            json={"UPRN": selected[1]},
            headers={
                "Accept": "application/json, text/javascript, */*; q=0.01",
                "Content-Type": "application/json",
            },
        )
        data = r.json()

        if not data.get("SuccessFlag"):
            from api.councils._base import AddressNotFound

            raise AddressNotFound(
                f"No Tandridge collections found for {address.house_number!r}"
            )

        collections = []
        for item in data.get("lstCollections") or []:
            service = (item.get("Service") or "").strip()
            date_str = item.get("Date")
            if not service or not date_str:
                continue
            day = datetime.strptime(date_str, "%d/%m/%Y %H:%M:%S").date()
            collections.append(Collection(day, service))

        return collections


SCRAPER = Tandridge()
