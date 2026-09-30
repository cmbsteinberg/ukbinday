"""West Oxfordshire: Salesforce Aura flow lookup for a property's waste collections."""

from __future__ import annotations

import json
import re
from datetime import date, timedelta
from typing import Any

from api.councils._base import (
    Address,
    Collection,
    Http,
    Meta,
    Response,
    Scraper,
    UpstreamError,
    match_address,
    parse_date,
)

_API_URL = "https://community.westoxon.gov.uk/s/sfsites/aura"
_SEARCH_PAGE = "https://community.westoxon.gov.uk/s/waste-collection-enquiry"
_AURA_CONFIG = re.compile(r"var\s+auraConfig\s*=\s*(.*?),\n")
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:115.0) Gecko/20100101 Firefox/115.0",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


def _parse_date(date_str: str) -> date:
    if date_str.lower() == "today":
        return date.today()
    if date_str.lower() == "tomorrow":
        return date.today() + timedelta(days=1)
    return parse_date(date_str)


async def _load_aura_context(http: Http) -> str:
    r = await http.get(_SEARCH_PAGE)
    match = _AURA_CONFIG.search(r.text, re.MULTILINE)
    if match is None:
        raise UpstreamError("Could not find West Oxfordshire Aura config")

    fwuid = json.loads(match.group(1))["context"]["fwuid"]
    return json.dumps(
        {
            "mode": "PROD",
            "fwuid": fwuid,
            "app": "siteforce:communityApp",
            "loaded": {
                "APPLICATION@markup://siteforce:communityApp": "vgD8vvaBHzgKYqb_JQjQdw",
                "COMPONENT@markup://flowruntime:flowRuntimeForFlexiPage": "6vLCX6RcjM4U8N2_kygrQw",
                "COMPONENT@markup://instrumentation:o11ySecondaryLoader": "1JitVv-ZC5qlK6HkuofJqQ",
            },
            "dn": [],
            "globals": {},
            "uad": False,
        }
    )


async def _request(
    http: Http,
    aura_context: str,
    r: int,
    aura_method: str,
    message: dict[str, Any] | str,
) -> Response:
    if isinstance(message, dict):
        message = json.dumps(message)
    return await http.post(
        _API_URL,
        params={"r": r, aura_method: 1},
        data={
            "message": message,
            "aura.context": aura_context,
            "aura.pageURI": "/s/waste-collection-enquiry",
            "aura.token": "null",
        },
    )


class WestOxfordshire(Scraper):
    meta = Meta(
        title="West Oxfordshire District Council",
        url="https://westoxon.gov.uk/",
        lads=("E07000181",),
        cases={
            "75 manor road woodstock": {
                "address": "75 manor road woodstock, ox20 1xr",
                "house_number": "75",
                "street": "Manor Road",
                "postcode": "OX20 1XR",
            },
            "65 main road long hanborough": {
                "address": "65 MAIN ROAD, LONG HANBOROUGH, WITNEY, OX29 8JX",
                "house_number": "65",
                "street": "Main Road",
                "postcode": "OX29 8JX",
            },
        },
    )
    requires = frozenset({"label"})
    headers = _HEADERS
    verify_tls = False

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        search_address = address.need("label")
        aura_context = await _load_aura_context(http)

        message1 = {
            "actions": [
                {
                    "id": "85;a",
                    "descriptor": "aura://FlowRuntimeConnectController/ACTION$startFlow",
                    "callingDescriptor": "UNKNOWN",
                    "params": {
                        "flowDevName": "WebFormAlloyWasteCollectionEnquiry",
                        "arguments": '[{"name":"vClientCode","type":"String","supportsRecordId":false,"value":"WOD"}]',
                        "enableTrace": False,
                        "enableRollbackMode": False,
                        "debugAsUserId": "",
                        "useLatestSubflow": False,
                    },
                }
            ]
        }
        r = await _request(
            http, aura_context, 5, "aura.FlowRuntimeConnect.startFlow", message1
        )
        serialized_state = r.json()["actions"][0]["returnValue"]["response"][
            "serializedEncodedState"
        ]

        message2 = {
            "actions": [
                {
                    "id": "89;a",
                    "descriptor": "aura://LookupController/ACTION$lookup",
                    "callingDescriptor": "UNKNOWN",
                    "params": {
                        "objectApiName": "Case",
                        "fieldApiName": "Property__c",
                        "pageParam": 1,
                        "pageSize": 25,
                        "q": search_address,
                        "searchType": "TypeAhead",
                        "targetApiName": "Property__c",
                        "body": {
                            "sourceRecord": {"apiName": "Case", "fields": {"Id": None}}
                        },
                    },
                }
            ]
        }
        r = await _request(
            http,
            aura_context,
            1,
            "aura.LookupController.lookupaura.Lookup.lookup",
            message2,
        )

        candidates = r.json()["actions"][0]["returnValue"]["lookupResults"][
            "Property__c"
        ]["records"]

        def candidate_text(candidate: dict[str, Any]) -> str:
            return candidate["fields"]["Name"]["value"] or ""

        selected = match_address(address, candidates, text=candidate_text)
        address_id = selected["id"]
        address_name = candidate_text(selected)

        message3 = {
            "actions": [
                {
                    "id": "114;a",
                    "descriptor": "aura://RecordUiController/ACTION$getRecordWithFields",
                    "callingDescriptor": "UNKNOWN",
                    "params": {"recordId": address_id, "fields": ["Property__c.Name"]},
                }
            ]
        }
        await _request(
            http, aura_context, 25, "aura.RecordUi.getRecordWithFields", message3
        )

        message4 = {
            "actions": [
                {
                    "id": "123;a",
                    "descriptor": "aura://FlowRuntimeConnectController/ACTION$navigateFlow",
                    "callingDescriptor": "UNKNOWN",
                    "params": {
                        "request": {
                            "action": "NEXT",
                            "serializedState": serialized_state,
                            "fields": [
                                {
                                    "field": "Property.recordId",
                                    "value": address_id,
                                    "isVisible": True,
                                },
                                {
                                    "field": "Property.recordIds",
                                    "value": [address_id],
                                    "isVisible": True,
                                },
                                {
                                    "field": "Property.recordName",
                                    "value": address_name,
                                    "isVisible": True,
                                },
                            ],
                            "uiElementVisited": True,
                            "enableTrace": False,
                            "lcErrors": {},
                        }
                    },
                }
            ]
        }
        r = await _request(
            http, aura_context, 26, "aura.FlowRuntimeConnect.navigateFlow", message4
        )
        serialized_state = r.json()["actions"][0]["returnValue"]["response"][
            "serializedEncodedState"
        ]

        message5 = {
            "actions": [
                {
                    "id": "125;a",
                    "descriptor": "aura://FlowRuntimeConnectController/ACTION$navigateFlow",
                    "callingDescriptor": "UNKNOWN",
                    "params": {
                        "request": {
                            "action": "CONTINUE_AFTER_COMMIT",
                            "serializedState": serialized_state,
                            "fields": [],
                            "uiElementVisited": True,
                            "enableTrace": False,
                        }
                    },
                }
            ]
        }
        r = await _request(
            http, aura_context, 27, "aura.FlowRuntimeConnect.navigateFlow", message5
        )
        serialized_state = r.json()["actions"][0]["returnValue"]["response"][
            "serializedEncodedState"
        ]

        message6 = {
            "actions": [
                {
                    "id": "127;a",
                    "descriptor": "aura://FlowRuntimeConnectController/ACTION$navigateFlow",
                    "callingDescriptor": "UNKNOWN",
                    "params": {
                        "request": {
                            "action": "CONTINUE_AFTER_COMMIT",
                            "serializedState": serialized_state,
                            "fields": [],
                            "uiElementVisited": True,
                            "enableTrace": False,
                        }
                    },
                }
            ]
        }
        r = await _request(
            http, aura_context, 28, "aura.FlowRuntimeConnect.navigateFlow", message6
        )

        table_value = r.json()["actions"][0]["returnValue"]["response"]["fields"][1][
            "inputs"
        ][3]["value"]
        table = json.loads(table_value)

        collections = []
        for row in table:
            date_str = row["col2"]
            bin_type = row["col1"]
            try:
                collection_date = _parse_date(date_str)
            except ValueError:
                continue
            collections.append(Collection(collection_date, bin_type))
        return collections


SCRAPER = WestOxfordshire()
