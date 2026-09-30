"""Forest of Dean: Salesforce Aura flow lookup for waste collections by property address."""

from __future__ import annotations

import json
import re
from datetime import date, timedelta
from typing import Any

from api.councils._base import (
    Address,
    Collection,
    Http,
    InputError,
    Meta,
    Scraper,
    UpstreamError,
    match_address,
    parse_date,
)

API_URL = "https://community.fdean.gov.uk/s/sfsites/aura"
SEARCH_PAGE = "https://community.fdean.gov.uk/s/waste-collection-enquiry"
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:115.0) Gecko/20100101 Firefox/115.0",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}
_AURA_CONFIG = re.compile(r"var\s+auraConfig\s*=\s*(.*?),\n")


def _parse_date(date_str: str) -> date:
    if date_str.lower() == "today":
        return date.today()
    if date_str.lower() == "tomorrow":
        return date.today() + timedelta(days=1)
    return parse_date(date_str)


async def _request(
    http: Http,
    r: int,
    aura_method: str,
    message: dict[str, Any] | str,
    aura_context: str,
) -> Any:
    if isinstance(message, dict):
        message = json.dumps(message)
    response = await http.post(
        API_URL,
        params={"r": r, aura_method: 1},
        data={
            "message": message,
            "aura.context": aura_context,
            "aura.pageURI": "/s/waste-collection-enquiry",
            "aura.token": "null",
        },
    )
    return response


def _record_name(record: dict[str, Any]) -> str:
    value = record["fields"]["Name"]["value"]
    return value if isinstance(value, str) else ""


class ForestOfDean(Scraper):
    meta = Meta(
        title="Forest of Dean District Council",
        url="https://www.fdean.gov.uk/",
        lads=("E07000080",),
        cases={
            "Southfield Road, Coleford": {
                "house_number": "8",
                "street": "SOUTHFIELD ROAD",
                "postcode": "GL16 8BZ",
            },
            "Wynols Close, Broadwell": {
                "house_number": "36",
                "street": "WYNOLS CLOSE",
                "postcode": "GL16 7RR",
            },
        },
    )
    requires = frozenset()
    headers = _HEADERS
    verify_tls = False

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        page = await http.get(SEARCH_PAGE)
        aura_match = _AURA_CONFIG.search(page.text, re.MULTILINE)
        if aura_match is None:
            raise UpstreamError("Forest of Dean page has no Aura configuration")

        try:
            context_data = json.loads(aura_match.group(1))
            aura_context = json.dumps(
                {
                    "mode": "PROD",
                    "fwuid": context_data["context"]["fwuid"],
                    "app": "siteforce:communityApp",
                    "loaded": context_data["context"]["loaded"],
                    "dn": [],
                    "globals": {},
                    "uad": False,
                }
            )
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            raise UpstreamError("Forest of Dean page has invalid Aura configuration") from exc

        search_text = address.label or address.first_line
        if not search_text:
            raise InputError("Forest of Dean needs an address")

        message1 = {
            "actions": [
                {
                    "id": "85;a",
                    "descriptor": "aura://FlowRuntimeConnectController/ACTION$startFlow",
                    "callingDescriptor": "UNKNOWN",
                    "params": {
                        "flowDevName": "WebFormAlloyWasteCollectionEnquiry",
                        "arguments": '[{"name":"vClientCode","type":"String","supportsRecordId":false,"value":"FOD"}]',
                        "enableTrace": False,
                        "enableRollbackMode": False,
                        "debugAsUserId": "",
                        "useLatestSubflow": False,
                    },
                }
            ]
        }
        response = await _request(
            http, 5, "aura.FlowRuntimeConnect.startFlow", message1, aura_context
        )
        serialized_state = response.json()["actions"][0]["returnValue"]["response"][
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
                        "q": search_text,
                        "searchType": "TypeAhead",
                        "targetApiName": "Property__c",
                        "body": {
                            "sourceRecord": {"apiName": "Case", "fields": {"Id": None}}
                        },
                    },
                }
            ]
        }
        response = await _request(
            http,
            1,
            "aura.LookupController.lookupaura.Lookup.lookup",
            message2,
            aura_context,
        )

        records = response.json()["actions"][0]["returnValue"]["lookupResults"][
            "Property__c"
        ]["records"]
        candidates = [
            record
            for record in records
            if isinstance(record, dict) and _record_name(record)
        ]
        selected = match_address(address, candidates, text=_record_name)
        address_id = selected["id"]
        address_name = _record_name(selected)

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
            http, 25, "aura.RecordUi.getRecordWithFields", message3, aura_context
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
        response = await _request(
            http, 26, "aura.FlowRuntimeConnect.navigateFlow", message4, aura_context
        )
        serialized_state = response.json()["actions"][0]["returnValue"]["response"][
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
        response = await _request(
            http, 27, "aura.FlowRuntimeConnect.navigateFlow", message5, aura_context
        )
        serialized_state = response.json()["actions"][0]["returnValue"]["response"][
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
        response = await _request(
            http, 28, "aura.FlowRuntimeConnect.navigateFlow", message6, aura_context
        )

        table_value = response.json()["actions"][0]["returnValue"]["response"][
            "fields"
        ][1]["inputs"][3]["value"]
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


SCRAPER = ForestOfDean()
