"""Stockton-on-Tees: submit the UPRN through its session-backed bin dates form."""

from __future__ import annotations

import base64
import binascii
import json
import re
from datetime import datetime

from bs4 import Tag

from api.councils._base import (
    Address,
    Collection,
    Http,
    Meta,
    Scraper,
    Transport,
    UpstreamError,
    find_tag,
    soup,
)

_API_URL = "https://www.stockton.gov.uk/bin-collection-days"
_FORM_ID = "LOOKUPBINDATESBYADDRESSSKIPOUTOFREGIONV2_FORM"
_FORM_DATA_PATTERN = re.compile(
    r'var LOOKUPBINDATESBYADDRESSSKIPOUTOFREGIONV2FormData = "(.*?)";$',
    re.MULTILINE | re.DOTALL,
)


class StocktonOnTees(Scraper):
    meta = Meta(
        title="Stockton-on-Tees Borough Council",
        url="https://www.stockton.gov.uk/",
        lads=("E06000004",),
        cases={
            "100110203615": {"uprn": "100110203615"},
            "100110160417": {"uprn": "100110160417"},
            "20002027430": {"uprn": "20002027430"},
        },
    )
    requires = frozenset({"uprn"})
    transport = Transport.CURL_CFFI

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        r = await http.get(_API_URL, timeout=30)
        page = soup(r.text)

        form = page.find("form", attrs={"id": _FORM_ID})
        if not isinstance(form, Tag) or not form.get("action"):
            raise UpstreamError(f"Could not find {_FORM_ID} or its action")
        form_url = form["action"]

        page_session_input = page.find(
            "input",
            attrs={"name": "LOOKUPBINDATESBYADDRESSSKIPOUTOFREGIONV2_PAGESESSIONID"},
        )
        session_input = page.find(
            "input",
            attrs={"name": "LOOKUPBINDATESBYADDRESSSKIPOUTOFREGIONV2_SESSIONID"},
        )
        nonce_input = page.find(
            "input",
            attrs={"name": "LOOKUPBINDATESBYADDRESSSKIPOUTOFREGIONV2_NONCE"},
        )

        page_session_id = (
            page_session_input.get("value") if isinstance(page_session_input, Tag) else None
        )
        session_id = session_input.get("value") if isinstance(session_input, Tag) else None
        nonce = nonce_input.get("value") if isinstance(nonce_input, Tag) else None
        if not page_session_id:
            raise UpstreamError(
                "Could not find LOOKUPBINDATESBYADDRESSSKIPOUTOFREGIONV2_PAGESESSIONID"
            )
        if not session_id:
            raise UpstreamError(
                "Could not find LOOKUPBINDATESBYADDRESSSKIPOUTOFREGIONV2_SESSIONID"
            )
        if not nonce:
            raise UpstreamError(
                "Could not find LOOKUPBINDATESBYADDRESSSKIPOUTOFREGIONV2_NONCE"
            )

        form_data = {
            "LOOKUPBINDATESBYADDRESSSKIPOUTOFREGIONV2_PAGESESSIONID": page_session_id,
            "LOOKUPBINDATESBYADDRESSSKIPOUTOFREGIONV2_SESSIONID": session_id,
            "LOOKUPBINDATESBYADDRESSSKIPOUTOFREGIONV2_NONCE": nonce,
            "LOOKUPBINDATESBYADDRESSSKIPOUTOFREGIONV2_FORMACTION_NEXT": (
                "LOOKUPBINDATESBYADDRESSSKIPOUTOFREGIONV2_FINDBUTTON"
            ),
            "LOOKUPBINDATESBYADDRESSSKIPOUTOFREGIONV2_UPRN": address.need("uprn"),
            "LOOKUPBINDATESBYADDRESSSKIPOUTOFREGIONV2_CUSTODIAN": "738",
        }

        r = await http.post(form_url, data=form_data, timeout=30)
        page = soup(r.text)
        script = find_tag(page, "script", string=_FORM_DATA_PATTERN, what="Could not find LOOKUPBINDATESBYADDRESSSKIPOUTOFREGIONV2FormData in response")
        match = _FORM_DATA_PATTERN.search(script.get_text())
        if not match:
            raise UpstreamError(
                "Could not extract LOOKUPBINDATESBYADDRESSSKIPOUTOFREGIONV2FormData value"
            )

        try:
            decoded_data = base64.b64decode(match.group(1))
            data = json.loads(decoded_data)
        except (binascii.Error, json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise UpstreamError("Could not decode Stockton's collection data") from exc

        collections: list[Collection] = []
        try:
            page_order = data["_PAGEORDER_"]
        except (KeyError, TypeError) as exc:
            raise UpstreamError("Stockton's response has no collection page order") from exc

        for key in page_order:
            try:
                details = data[key]["COLLECTIONDETAILS2"]
            except (KeyError, TypeError) as exc:
                raise UpstreamError("Stockton's response has no collection details") from exc

            details_page = soup(details)
            for waste_type_div in details_page.find_all(
                "div", attrs={"class": "grid__cell"}
            ):
                title_node = waste_type_div.find(
                    "p", attrs={"class": "myaccount-block__title--bin"}
                )
                try:
                    waste_type = title_node.text.strip()
                except AttributeError:
                    continue

                date_nodes = waste_type_div.find_all(
                    "p", attrs={"class": "myaccount-block__date--bin"}
                )

                # Garden waste dates use a different part of the page.
                if date_nodes is None or len(date_nodes) == 0:
                    try:
                        date_nodes = [
                            waste_type_div.find_all("p")[1].find_all("strong")[i]
                            for i in range(2)
                        ]
                    except (AttributeError, IndexError):
                        continue

                for date_node in date_nodes:
                    try:
                        date_string = re.sub(
                            r"(?<=[0-9])(?:st|nd|rd|th)",
                            "",
                            date_node.text.strip(),
                        )
                        day = datetime.strptime(date_string, "%a %d %B %Y").date()
                    except (ValueError, AttributeError):
                        continue
                    collections.append(Collection(day, waste_type))

        return collections


SCRAPER = StocktonOnTees()
