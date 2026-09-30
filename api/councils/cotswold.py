"""Cotswold: Salesforce Aura flow lookup using the full address label."""

from __future__ import annotations

import json
import logging
import re
from datetime import date, timedelta
from typing import Any

from api.councils._base import (
    Address,
    AddressNotFound,
    Collection,
    Http,
    Meta,
    Scraper,
    UpstreamError,
    parse_date,
)
from api.councils._base.http import Response

_LOGGER = logging.getLogger(__name__)

_API_URL = "https://community.cotswold.gov.uk/s/sfsites/aura"
_SEARCH_PAGE = "https://community.cotswold.gov.uk/s/waste-collection-enquiry"
_AURA_CONFIG = re.compile(r"var\s+auraConfig\s*=\s*(.*?),\n")

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:115.0) Gecko/20100101 Firefox/115.0",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


async def _aura_context(http: Http) -> str:
    response = await http.get(_SEARCH_PAGE)
    match = _AURA_CONFIG.search(response.text, re.MULTILINE)
    if match is None:
        raise UpstreamError("Could not find Cotswold Aura config")

    try:
        config = json.loads(match.group(1))
        context = config["context"]
        return json.dumps(
            {
                "mode": "PROD",
                "fwuid": context["fwuid"],
                "app": "siteforce:communityApp",
                "loaded": context["loaded"],
                "dn": [],
                "globals": {},
                "uad": False,
            }
        )
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise UpstreamError("Invalid Cotswold Aura config") from exc


async def _request(
    http: Http,
    aura_context: str,
    request_id: int,
    aura_method: str,
    message: dict[str, Any] | str,
) -> Response:
    serialized_message = json.dumps(message) if isinstance(message, dict) else message
    return await http.post(
        _API_URL,
        params={"r": request_id, aura_method: 1},
        data={
            "message": serialized_message,
            "aura.context": aura_context,
            "aura.pageURI": "/s/waste-collection-enquiry",
            "aura.token": "null",
        },
    )


def _parse_date(date_text: str) -> date:
    if date_text.lower() == "today":
        return date.today()
    if date_text.lower() == "tomorrow":
        return date.today() + timedelta(days=1)
    return parse_date(date_text)


class Cotswold(Scraper):
    meta = Meta(
        title="Cotswold District Council",
        url="https://www.cotswold.gov.uk/",
        lads=("E07000079",),
        cases={
            "Parsons Piece, 1 Glebe Lane, Kemble, Cirencester": {
                "address": "PARSONS PIECE, 1 GLEBE LANE, KEMBLE, CIRENCESTER, GL7 6BD"
            },
        },
    )
    requires = frozenset({"label"})
    headers = _HEADERS
    verify_tls = False

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        address_label = address.need("label")
        aura_context = await _aura_context(http)

        message1 = {
            "actions": [
                {
                    "id": "85;a",
                    "descriptor": "aura://FlowRuntimeConnectController/ACTION$startFlow",
                    "callingDescriptor": "UNKNOWN",
                    "params": {
                        "flowDevName": "WebFormAlloyWasteCollectionEnquiry",
                        "arguments": '[{"name":"vClientCode","type":"String","supportsRecordId":false,"value":"CDC"}]',
                        "enableTrace": False,
                        "enableRollbackMode": False,
                        "debugAsUserId": "",
                        "useLatestSubflow": False,
                    },
                }
            ]
        }
        response = await _request(
            http, aura_context, 5, "aura.FlowRuntimeConnect.startFlow", message1
        )
        try:
            serialized_state = response.json()["actions"][0]["returnValue"]["response"][
                "serializedEncodedState"
            ]
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise UpstreamError("Invalid Cotswold flow response") from exc

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
                        "q": address_label,
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
            aura_context,
            1,
            "aura.LookupController.lookupaura.Lookup.lookup",
            message2,
        )

        try:
            addresses = response.json()["actions"][0]["returnValue"]["lookupResults"][
                "Property__c"
            ]["records"]
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise UpstreamError("Invalid Cotswold address lookup response") from exc

        address_id = None
        address_name = None
        address_set: set[str] = set()
        for candidate in addresses:
            potential_address = candidate["fields"]["Name"]["value"]
            address_set.add(potential_address)
            if (
                potential_address is not None
                and potential_address.lower().replace(" ", "").replace(".", "").replace(",", "")
                == address_label.lower().replace(" ", "").replace(".", "").replace(",", "")
            ):
                address_id = candidate["id"]
                address_name = potential_address
                break
        address_set -= {None, ""}
        if not address_id:
            raise AddressNotFound(
                f"No property matching {address_label!r} on Cotswold's list",
                sorted(address_set),
            )

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
        response = await _request(
            http, aura_context, 26, "aura.FlowRuntimeConnect.navigateFlow", message4
        )
        try:
            serialized_state = response.json()["actions"][0]["returnValue"]["response"][
                "serializedEncodedState"
            ]
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise UpstreamError("Invalid Cotswold flow response") from exc

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
            http, aura_context, 27, "aura.FlowRuntimeConnect.navigateFlow", message5
        )
        try:
            serialized_state = response.json()["actions"][0]["returnValue"]["response"][
                "serializedEncodedState"
            ]
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise UpstreamError("Invalid Cotswold flow response") from exc

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
            http, aura_context, 28, "aura.FlowRuntimeConnect.navigateFlow", message6
        )
        try:
            table_value = response.json()["actions"][0]["returnValue"]["response"][
                "fields"
            ][1]["inputs"][3]["value"]
            table = json.loads(table_value)
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise UpstreamError("Invalid Cotswold collection response") from exc

        collections = []
        for row in table:
            date_text = row["col2"]
            bin_type = row["col1"]
            try:
                collection_date = _parse_date(date_text)
            except ValueError:
                _LOGGER.warning("date in unknown format: %s", date_text)
                continue
            collections.append(Collection(collection_date, bin_type))

        return collections


SCRAPER = Cotswold()
