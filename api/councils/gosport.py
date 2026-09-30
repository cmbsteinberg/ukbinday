"""Gosport: search its GOSS form by postcode, then fetch collections for the selected UPRN."""

from __future__ import annotations

import base64
import binascii
import json
import re
from datetime import datetime
from urllib.parse import parse_qs, urlparse

from api.councils._base import (
    Address,
    Collection,
    Http,
    Meta,
    Scraper,
    UpstreamError,
    soup,
)

TITLE = "Gosport Borough Council"
URL = "https://www.gosport.gov.uk/refuserecyclingdays"
FORM_NAME = "QUERYWARDSCOLLECTIONSWS"

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


def _parse_goss_ids(url: str) -> dict[str, str]:
    params = parse_qs(urlparse(url).query)
    try:
        return {
            "page_session_id": params["pageSessionId"][0],
            "session_id": params["fsid"][0],
            "nonce": params["fsn"][0],
        }
    except (KeyError, IndexError) as exc:
        raise UpstreamError("Gosport form action is missing session identifiers") from exc


def _parse_collections(html: str) -> list[Collection]:
    match = re.search(rf'{FORM_NAME}SerializedVariables\s*=\s*"([^"]+)"', html)
    if not match:
        raise UpstreamError("Could not find serialized variables in Gosport response")

    try:
        serialized = json.loads(base64.b64decode(match.group(1)))
    except (binascii.Error, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise UpstreamError("Could not decode Gosport collection response") from exc

    if "Recordset1" not in serialized:
        raise UpstreamError("No Recordset1 in Gosport response")

    recordset = serialized["Recordset1"]
    value = recordset.get("value", recordset) if isinstance(recordset, dict) else recordset
    result = value.get("GetCollectionByUprnAndDateResult", value)

    if not result.get("SuccessFlag"):
        raise UpstreamError(
            f"Gosport API error: {result.get('ErrorDescription', 'Unknown error')}"
        )

    collections_data = result.get("Collections")
    if not collections_data:
        return []

    collection_list = collections_data.get("Collection", [])
    if isinstance(collection_list, dict):
        collection_list = [collection_list]

    entries = []
    for item in collection_list:
        try:
            day = datetime.strptime(item["Date"], "%d/%m/%Y %H:%M:%S").date()
            service = item["Service"]
        except (KeyError, TypeError, ValueError) as exc:
            raise UpstreamError("Could not parse a Gosport collection") from exc
        entries.append(Collection(day, service))

    return entries


class Gosport(Scraper):
    meta = Meta(
        title=TITLE,
        url=URL,
        lads=("E07000088",),
        cases={
            "PO12 4RL, 1 Holland House": {"postcode": "PO12 4RL", "uprn": "37020212"},
            "PO12 2EL, 10 Testcombe Road": {"postcode": "PO12 2EL", "uprn": "37030710"},
        },
    )
    requires = frozenset({"postcode", "uprn"})
    headers = _HEADERS

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        postcode = address.need("postcode")
        uprn = address.need("uprn")

        r = await http.get(URL)
        page = soup(r.text)
        form = page.find(id=f"{FORM_NAME}_FORM")
        if form is None or not form.get("action"):
            raise UpstreamError("Could not find GOSS form on Gosport page")

        action_url = form["action"]
        goss_ids = _parse_goss_ids(action_url)

        search_data = {
            f"{FORM_NAME}_PAGESESSIONID": goss_ids["page_session_id"],
            f"{FORM_NAME}_SESSIONID": goss_ids["session_id"],
            f"{FORM_NAME}_NONCE": goss_ids["nonce"],
            f"{FORM_NAME}_VARIABLES": "",
            f"{FORM_NAME}_PAGENAME": "PAGE1",
            f"{FORM_NAME}_PAGEINSTANCE": "0",
            f"{FORM_NAME}_PAGE1_SEARCHED": "NO",
            f"{FORM_NAME}_PAGE1_SEARCHADDRESS": "YES",
            f"{FORM_NAME}_PAGE1_NEXTPAGE": "PAGE2",
            f"{FORM_NAME}_PAGE1_POSTCODE": postcode,
            f"{FORM_NAME}_PAGE1_PROPERTY": "",
            f"{FORM_NAME}_PAGE1_REFNO": "",
            f"{FORM_NAME}_PAGE1_UPRN": "",
            f"{FORM_NAME}_FORMACTION_NEXT": f"{FORM_NAME}_PAGE1_GETADDRESSES",
        }
        r = await http.post(action_url, data=search_data)
        page = soup(r.text)
        form = page.find(id=f"{FORM_NAME}_FORM")
        if form is None or not form.get("action"):
            raise UpstreamError("Could not find GOSS form after address search")

        action_url = form["action"]
        goss_ids = _parse_goss_ids(action_url)

        variables = {
            "SEARCHREF": uprn,
            "SEARCHUPRN": uprn,
        }
        encoded_vars = base64.b64encode(json.dumps(variables).encode()).decode()

        submit_data = {
            f"{FORM_NAME}_PAGESESSIONID": goss_ids["page_session_id"],
            f"{FORM_NAME}_SESSIONID": goss_ids["session_id"],
            f"{FORM_NAME}_NONCE": goss_ids["nonce"],
            f"{FORM_NAME}_VARIABLES": encoded_vars,
            f"{FORM_NAME}_PAGENAME": "PAGE1",
            f"{FORM_NAME}_PAGEINSTANCE": "0",
            f"{FORM_NAME}_PAGE1_SEARCHED": "YES",
            f"{FORM_NAME}_PAGE1_SEARCHADDRESS": "NO",
            f"{FORM_NAME}_PAGE1_NEXTPAGE": "PAGE2",
            f"{FORM_NAME}_PAGE1_POSTCODE": postcode,
            f"{FORM_NAME}_PAGE1_PROPERTY": uprn,
            f"{FORM_NAME}_PAGE1_REFNO": uprn,
            f"{FORM_NAME}_PAGE1_UPRN": uprn,
            f"{FORM_NAME}_FORMACTION_NEXT": f"{FORM_NAME}_PAGE1_FIELD9",
        }
        r = await http.post(action_url, data=submit_data)
        return _parse_collections(r.text)


SCRAPER = Gosport()
