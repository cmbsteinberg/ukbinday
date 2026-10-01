"""Buckinghamshire: iTouchVision "gdsv5" portal, six encrypted calls, UPRN only.

The portal is a form engine. We read the form's web-service step, open a report
(a session), then run the step with the UPRN. It answers with an HTML fragment
holding the *next* collection per bin, so the module yields one date per bin type.
"""

from __future__ import annotations

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
    soup,
    text_of,
)
from api.councils._platforms.itouchvision import decrypt, encrypt

BASE = "https://itouchvision.app/portal/itouchvision/gdsv5"
# The category (the "find out when your bin collection" form) in the portal's own ids.
CATEGORY_UID = "1620D584419C7043A8323332E0634D00A8C0D5EF"
_JSON = {"Content-Type": "application/json; charset=UTF-8"}


class Buckinghamshire(Scraper):
    meta = Meta(
        title="Buckinghamshire Council",
        url="https://www.buckinghamshire.gov.uk/waste-and-recycling/bin-collections/find-out-when-its-your-bin-collection/",
        lads=("E06000060",),
        cases={
            "High Wycombe": {"uprn": "100081093078"},
            "Aylesbury": {"uprn": "766323596"},
            "Chalfont St Peter": {"uprn": "100080517055"},
        },
    )
    requires = frozenset({"uprn"})

    async def _get(self, http: Http, endpoint: str, payload: dict[str, Any]) -> Any:
        r = await http.get(f"{BASE}/{endpoint}", headers={"P_PARAMETER": encrypt(payload)})
        return self._decode(r.text)

    async def _post(self, http: Http, endpoint: str, payload: dict[str, Any]) -> Any:
        r = await http.post(f"{BASE}/{endpoint}", content=encrypt(payload), headers=_JSON)
        return self._decode(r.text)

    @staticmethod
    def _decode(text: str) -> Any:
        try:
            return decrypt(text)
        except ValueError as e:  # not hex, bad padding or not JSON: the portal sent something else
            raise UpstreamError(f"Unreadable iTouchVision response: {text[:100]!r}") from e

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        uprn = address.need("uprn")

        try:
            link = (await self._get(http, "service/getcategorylinkdata", {"P_CAT_UID": CATEGORY_UID}))[
                "CATEGORY_LINK"
            ][0]
            client = await self._get(
                http, "util/igetclientdetails", {"P_UID": link["ITV_APEX_URL"], "P_LANGUAGE_CODE": "EN"}
            )
            base = {
                "P_CLIENT_ID": client["P_CLIENT_ID"],
                "P_ACCESS_KEY": client["P_ACCESS_KEY"],
                "LANG_CODE": "EN",
            }
            form = await self._get(
                http,
                "plugin/getformdata",
                {**base, "P_CATEGORY_ID": link["CATEGORY_ID"], "P_REPORT_ID": "", "P_USER_ID": None},
            )
            step = next(
                item
                for page in form["PAGES"]
                for region in page.get("REGIONS", [])
                for item in region.get("ITEMS", [])
                if item.get("I_TYPE") == "WEB_SERVICE_REF"
            )
            step_ids = {"P_ITEM_ID": step["I_ID"], "P_WS_ID": step["I_WS_ID"]}
            mapping = await self._get(
                http, "plugin/getWSRInputMapping", {**base, **step_ids, "P_REPORT_ID": "", "P_USER_ID": None}
            )
            report = await self._post(
                http,
                "service/saveqadata",
                {
                    "P_ACCESS_KEY": client["P_ACCESS_KEY"],
                    "P_APP_ID": 0,
                    "P_REPORT_ID": None,
                    "P_USER_ID": None,
                    "P_CATEGORY_ID": link["CATEGORY_ID"],
                    "P_CLIENT_ID": client["P_CLIENT_ID"],
                    "P_COUNCIL_ID": client["P_COUNCIL_ID"],
                    "P_FORM_ID": form["F_ID"],
                    "P_LANGUAGE_CODE": "EN",
                    "P_ALLOW_START_PAGE": 1,
                    "P_SKIPPED_PAGE_ID": "",
                    "P_PAGE_ID": form["PAGES"][0]["P_ID"],
                    "P_REPORT_DATA": [],
                },
            )
            result = await self._get(
                http,
                "plugin/getWSRResult",
                {
                    **base,
                    **step_ids,
                    "P_REPORT_ID": report["P_REPORT_ID"],
                    "P_INPUT_DATA": {mapping["WS_INPUTS"][0]["label"]: uprn},
                },
            )
        except (KeyError, IndexError, StopIteration, TypeError) as e:
            raise UpstreamError(f"iTouchVision portal changed shape: {e!r}") from e

        fragments = [
            out.get("VAL") or ""
            for out in (result.get("WSR_VALUE") or {}).get("OUTPUT_DATA", [])
            if out.get("OP_TYPE") == "SAVE_TO_ITEM"
        ]
        collections = []
        for fragment in fragments:
            for row in soup(fragment).select("table.govuk-table tbody tr"):
                cells = [text_of(td) for td in row.find_all("td")]
                if len(cells) < 2:
                    continue
                try:
                    day = parse_date(cells[0])
                except ValueError:
                    continue
                collections.append(Collection(day, cells[1]))

        if not collections:
            raise AddressNotFound(f"No collections for UPRN {uprn} in Buckinghamshire")
        return collections


SCRAPER = Buckinghamshire()
