"""Salesforce Experience Cloud "waste collection enquiry" flow, `community.<council>.gov.uk`.

Used by Forest of Dean, West Oxfordshire and Cotswold, which share one Salesforce
org's flow (`WebFormAlloyWasteCollectionEnquiry`), told apart by `vClientCode`.
Every site runs the same Aura calls against `/s/sfsites/aura`:

1. `GET /s/waste-collection-enquiry` and read `auraConfig` (the framework uid,
   and the loaded-component versions) out of the page.
2. `startFlow`, which returns the flow's serialized state.
3. A property `lookup` on the address text, then pick the property's record.
4. `getRecordWithFields`, then three `navigateFlow` steps (NEXT with the
   property, then CONTINUE_AFTER_COMMIT twice). The last answer holds the
   collections as a JSON table (`col1` bin, `col2` date) in a flow field.

What differs per council is data, in `SalesforceFlowConfig`. This is not the
Aura flow of Chesterfield or Guildford, which call their own Apex actions.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from api.councils._base import (
    Address,
    AddressNotFound,
    Collection,
    Http,
    InputError,
    Platform,
    Response,
    UpstreamError,
    match_address,
    parse_date,
)

_AURA_CONFIG = re.compile(r"var\s+auraConfig\s*=\s*(.*?),\n")
_PAGE_PATH = "/s/waste-collection-enquiry"
_FLOW = "WebFormAlloyWasteCollectionEnquiry"


@dataclass(frozen=True, slots=True, kw_only=True)
class SalesforceFlowConfig:
    host: str
    """The community site: "community.fdean.gov.uk"."""
    client_code: str
    """The flow's `vClientCode` argument: "FOD"."""
    loaded: Mapping[str, str] | None = None
    """Component versions for `aura.context`. None takes them from the page's
    `auraConfig`; a council whose page doesn't list the ones its API wants pins them."""
    label_only: bool = False
    """Search with the frontend's full address label, which the council needs
    (requires `label`). Otherwise the label or, failing that, the first line."""
    exact_label: bool = False
    """Accept only the property whose name equals the label (ignoring case, spaces,
    dots and commas) instead of `match_address`."""


def _squash(text: str) -> str:
    return text.lower().replace(" ", "").replace(".", "").replace(",", "")


def _record_name(record: dict[str, Any]) -> str:
    value = record["fields"]["Name"]["value"]
    return value if isinstance(value, str) else ""


def _parse_date(text: str) -> date:
    if text.lower() == "today":
        return date.today()
    if text.lower() == "tomorrow":
        return date.today() + timedelta(days=1)
    return parse_date(text)


def _message(action_id: str, descriptor: str, params: dict[str, Any]) -> dict[str, Any]:
    return {
        "actions": [
            {
                "id": action_id,
                "descriptor": descriptor,
                "callingDescriptor": "UNKNOWN",
                "params": params,
            }
        ]
    }


def _return_value(response: Response, what: str) -> Any:
    """The first action's `returnValue`, or `UpstreamError` when the answer is malformed."""
    try:
        return response.json()["actions"][0]["returnValue"]
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise UpstreamError(f"Salesforce flow gave an unexpected {what} response") from exc


def _flow_state(response: Response) -> str:
    try:
        return str(_return_value(response, "flow")["response"]["serializedEncodedState"])
    except (KeyError, TypeError) as exc:
        raise UpstreamError("Salesforce flow response has no serialized state") from exc


class SalesforceFlow(Platform[SalesforceFlowConfig]):
    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:115.0) Gecko/20100101 Firefox/115.0",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    verify_tls = False

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.requires = frozenset({"label"}) if self.config.label_only else frozenset()

    async def _context(self, http: Http) -> str:
        page = await http.get(f"https://{self.config.host}{_PAGE_PATH}")
        found = _AURA_CONFIG.search(page.text)
        if found is None:
            raise UpstreamError(f"{self.meta.title} page has no Aura configuration")
        try:
            context = json.loads(found.group(1))["context"]
            loaded = self.config.loaded if self.config.loaded is not None else context["loaded"]
            return json.dumps(
                {
                    "mode": "PROD",
                    "fwuid": context["fwuid"],
                    "app": "siteforce:communityApp",
                    "loaded": loaded,
                    "dn": [],
                    "globals": {},
                    "uad": False,
                }
            )
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            raise UpstreamError(f"{self.meta.title} page has invalid Aura configuration") from exc

    async def _call(
        self, http: Http, context: str, request_id: int, method: str, message: dict[str, Any]
    ) -> Response:
        return await http.post(
            f"https://{self.config.host}/s/sfsites/aura",
            params={"r": request_id, method: 1},
            data={
                "message": json.dumps(message),
                "aura.context": context,
                "aura.pageURI": _PAGE_PATH,
                "aura.token": "null",
            },
        )

    async def _navigate(
        self, http: Http, context: str, request_id: int, action_id: str, state: str, request: dict[str, Any]
    ) -> Response:
        message = _message(
            action_id,
            "aura://FlowRuntimeConnectController/ACTION$navigateFlow",
            {"request": {**request, "serializedState": state, "uiElementVisited": True, "enableTrace": False}},
        )
        return await self._call(http, context, request_id, "aura.FlowRuntimeConnect.navigateFlow", message)

    def _search_text(self, address: Address) -> str:
        if self.config.label_only:
            return address.need("label")
        text = address.label or address.first_line
        if not text:
            raise InputError(f"{self.meta.title} needs an address")
        return text

    def _pick(self, address: Address, search_text: str, records: list[Any]) -> dict[str, Any]:
        candidates = [r for r in records if isinstance(r, dict) and _record_name(r)]
        if not self.config.exact_label:
            return match_address(address, candidates, text=_record_name)
        wanted = _squash(search_text)
        for candidate in candidates:
            if _squash(_record_name(candidate)) == wanted:
                return candidate
        raise AddressNotFound(
            f"No property matching {search_text!r} on {self.meta.title}'s list",
            sorted({_record_name(c) for c in candidates}),
        )

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        search_text = self._search_text(address)
        context = await self._context(http)

        response = await self._call(
            http,
            context,
            5,
            "aura.FlowRuntimeConnect.startFlow",
            _message(
                "85;a",
                "aura://FlowRuntimeConnectController/ACTION$startFlow",
                {
                    "flowDevName": _FLOW,
                    "arguments": json.dumps(
                        [
                            {
                                "name": "vClientCode",
                                "type": "String",
                                "supportsRecordId": False,
                                "value": self.config.client_code,
                            }
                        ],
                        separators=(",", ":"),
                    ),
                    "enableTrace": False,
                    "enableRollbackMode": False,
                    "debugAsUserId": "",
                    "useLatestSubflow": False,
                },
            ),
        )
        state = _flow_state(response)

        response = await self._call(
            http,
            context,
            1,
            "aura.LookupController.lookupaura.Lookup.lookup",
            _message(
                "89;a",
                "aura://LookupController/ACTION$lookup",
                {
                    "objectApiName": "Case",
                    "fieldApiName": "Property__c",
                    "pageParam": 1,
                    "pageSize": 25,
                    "q": search_text,
                    "searchType": "TypeAhead",
                    "targetApiName": "Property__c",
                    "body": {"sourceRecord": {"apiName": "Case", "fields": {"Id": None}}},
                },
            ),
        )
        try:
            records = _return_value(response, "address lookup")["lookupResults"]["Property__c"]["records"]
        except (KeyError, TypeError) as exc:
            raise UpstreamError(f"{self.meta.title} address lookup has no property records") from exc
        try:
            selected = self._pick(address, search_text, records)
            property_id = selected["id"]
            property_name = _record_name(selected)
        except (KeyError, TypeError) as exc:
            raise UpstreamError(f"{self.meta.title} address lookup returned malformed records") from exc

        await self._call(
            http,
            context,
            25,
            "aura.RecordUi.getRecordWithFields",
            _message(
                "114;a",
                "aura://RecordUiController/ACTION$getRecordWithFields",
                {"recordId": property_id, "fields": ["Property__c.Name"]},
            ),
        )

        response = await self._navigate(
            http,
            context,
            26,
            "123;a",
            state,
            {
                "action": "NEXT",
                "fields": [
                    {"field": "Property.recordId", "value": property_id, "isVisible": True},
                    {"field": "Property.recordIds", "value": [property_id], "isVisible": True},
                    {"field": "Property.recordName", "value": property_name, "isVisible": True},
                ],
                "lcErrors": {},
            },
        )
        state = _flow_state(response)

        after_commit = {"action": "CONTINUE_AFTER_COMMIT", "fields": []}
        response = await self._navigate(http, context, 27, "125;a", state, after_commit)
        state = _flow_state(response)
        response = await self._navigate(http, context, 28, "127;a", state, after_commit)

        try:
            table = json.loads(_return_value(response, "collections")["response"]["fields"][1]["inputs"][3]["value"])
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise UpstreamError(f"{self.meta.title} flow gave no collection table") from exc

        collections = []
        for row in table:
            try:
                bin_type, date_text = row["col1"], row["col2"]
            except (KeyError, TypeError) as exc:
                raise UpstreamError(f"{self.meta.title} collection row has no col1/col2: {row!r}") from exc
            try:
                day = _parse_date(date_text)
            except ValueError as exc:
                raise UpstreamError(f"{self.meta.title}: date in unknown format: {date_text!r}") from exc
            collections.append(Collection(day, bin_type))
        return collections
