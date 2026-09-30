"""Knowsley: a Mendix flow searches by postcode, then selects the matching UPRN."""

from __future__ import annotations

import logging
import re
import time
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
)

_BASE_URL = "https://knowsleytransaction.mendixcloud.com/"
_INIT_URL = f"{_BASE_URL}link/youarebeingredirected?target=bincollectioninformation"
_API_URL = f"{_BASE_URL}xas/"
_INIT_PAYLOAD: dict[str, Any] = {
    "action": "get_session_data",
    "params": {
        "hybrid": False,
        "offline": False,
        "referrer": None,
        "profile": "",
        "timezoneoffset": -60,
        "timezoneId": "Europe/Berlin",
        "preferredLanguages": ["en-US", "en"],
        "version": 2,
    },
}
_LOGGER = logging.getLogger(__name__)


async def _do_request(
    http: Http,
    action: str,
    csrf_token: str,
    request_id: int,
    *,
    changes: dict[str, Any] | None = None,
    objects: list[dict[str, Any]] | None = None,
    params: dict[str, Any] | None = None,
    profile_data: dict[str, int] | None = None,
    operation_id: str | None = None,
    validation_guids: list[str] | None = None,
) -> dict[str, Any]:
    headers = {
        "Content-Type": "application/json",
        "x-csrf-token": csrf_token,
        "x-mx-reqtoken": f"{int(time.time())}-{request_id}",
    }
    payload: dict[str, Any] = {
        "action": action,
        "changes": changes or {},
        "objects": objects or [],
        "params": params or {},
        "profiledata": profile_data or {},
    }
    if operation_id:
        payload["operationId"] = operation_id
    if validation_guids:
        payload["validationGuids"] = validation_guids

    response = await http.post(_API_URL, json=payload, headers=headers, check=False)
    if response.status_code != 200:
        _LOGGER.error("error doing request: %s", response.text)
    if response.status_code >= 400:
        raise UpstreamError(f"HTTP {response.status_code} from {response.url}")
    return response.json()


class Knowsley(Scraper):
    meta = Meta(
        title="Knowsley Council",
        url="https://www.knowsley.gov.uk/",
        lads=("E08000011",),
        cases={
            "L364AR 000040082756": {"postcode": "L364AR", "uprn": "000040082756"},
            "L34 0HZ, 40029195": {"postcode": "L34 0HZ", "uprn": "40029195"},
        },
    )
    requires = frozenset({"postcode", "uprn"})

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        postcode = address.need("postcode")
        uprn = address.need("uprn")

        await http.get(_INIT_URL)
        response = await http.post(_API_URL, json=_INIT_PAYLOAD)
        init_data = response.json()

        objects = [init_data["objects"][1]]
        params: dict[str, Any] = {
            "actionname": "Service_YouAreBeingRedirected.SUB_YouAreBeingRedirected",
            "applyto": "selection",
            "guids": [init_data["objects"][1]["guid"]],
        }
        csrf_token = init_data["csrftoken"]
        cachebust = init_data["cachebust"]

        request_id = 3
        data = await _do_request(
            http,
            action="executeaction",
            csrf_token=csrf_token,
            request_id=request_id,
            objects=objects,
            params=params,
        )
        request_id += 1

        form_path = data["instructions"][0]["args"]["FormPath"]
        response = await http.get(
            f"{_BASE_URL}pages/en_US/{form_path}",
            params={cachebust: ""},
        )
        operation_ids = list(re.finditer(r'"config":{"operationId":"(.+?)",', response.text))
        try:
            operation_id_post = operation_ids[0].group(1)
            operation_id_uprn = operation_ids[1].group(1)
        except IndexError as exc:
            raise UpstreamError("Knowsley's enquiry page did not contain operation IDs") from exc

        objects = data["objects"]
        changes_postcode = data["changes"]
        changes_postcode[next(iter(changes_postcode.keys()))]["EnquiryPostcodeOrStreetName"] = {
            "value": postcode
        }

        params = {"OS_MissedBinEnquiry": {"guid": data["objects"][0]["guid"]}}
        validation_guids = [data["objects"][0]["guid"]]

        data = await _do_request(
            http,
            action="runtimeOperation",
            csrf_token=csrf_token,
            request_id=request_id,
            objects=objects,
            changes=changes_postcode,
            operation_id=operation_id_post,
            params=params,
            validation_guids=validation_guids,
        )
        request_id += 1

        uprn_change: tuple[str, dict[str, Any]] | None = None
        for change_id, change in data["changes"].items():
            if (
                "UPRN" in change
                and change["UPRN"]["value"].strip().strip("0") == uprn.strip().strip("0")
            ):
                uprn_change = (change_id, change)
                break

        if uprn_change is None:
            raise AddressNotFound(f"Knowsley has no property matching UPRN {uprn}")

        change_id, change = uprn_change
        objects += [next(obj for obj in data["objects"] if obj["guid"] == change_id)]
        params = {"Generic_Address": {"guid": objects[-1]["guid"]}}

        changes = changes_postcode.copy()
        changes[next(iter(changes.keys()))]["ShowAddressResults"] = {"value": True}
        changes.update({change_id: change})

        data = await _do_request(
            http,
            action="runtimeOperation",
            csrf_token=csrf_token,
            request_id=request_id,
            changes=changes,
            objects=objects,
            operation_id=operation_id_uprn,
            validation_guids=validation_guids,
            params=params,
        )

        collections: list[Collection] = []
        for change in data["changes"].values():
            for key, value in change.items():
                if not key.startswith("Next"):
                    continue
                date_text = value["value"]
                bin_type = key.replace("Next", "")
                try:
                    day = datetime.strptime(date_text, "%A %d/%m/%Y").date()
                except ValueError:
                    _LOGGER.warning("Could not parse date: %s for bin type %s", date_text, bin_type)
                    continue
                collections.append(Collection(day, bin_type))

        return collections


SCRAPER = Knowsley()
