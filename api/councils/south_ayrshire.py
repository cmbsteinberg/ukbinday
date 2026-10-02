"""South Ayrshire: submit the postcode, select the property by UPRN, and parse its collection schedule."""

from __future__ import annotations

import base64
import json
import re
from datetime import UTC, date, datetime, timedelta
from urllib.parse import parse_qs, urlparse

from bs4 import Tag

from api.councils._base import (
    Address,
    AddressNotFound,
    Blocker,
    Collection,
    Http,
    InputError,
    Meta,
    Scraper,
    Transport,
    UpstreamError,
    soup,
)

URL = "https://www.south-ayrshire.gov.uk"
COLLECTION_PAGE_URL = f"{URL}/article/23931/Bin-collection-days"


def _goss_ids(url: str) -> dict[str, str]:
    qs = parse_qs(urlparse(url).query)
    return {
        "page_session_id": qs["pageSessionId"][0],
        "session_id": qs["fsid"][0],
        "nonce": qs["fsn"][0],
    }


def _parse_collections(html: str) -> list[Collection]:
    match = re.search(r'var BINDAYSFormData = "([^"]+)";', html)
    if not match:
        raise UpstreamError("Could not find BINDAYSFormData in response")

    raw = match.group(1)
    raw += "=" * (-len(raw) % 4)
    try:
        data = json.loads(base64.b64decode(raw))
    except (ValueError, json.JSONDecodeError) as exc:
        raise UpstreamError("Could not parse BINDAYSFormData in response") from exc

    field15 = data.get("PAGE3_1", {}).get("FIELD15", {})
    if not field15.get("success"):
        errors = field15.get("errors", [])
        raise InputError(f"Collection lookup failed: {errors}")

    today = date.today()
    entries: list[Collection] = []

    for item in field15.get("calArray", []):
        bin_name = item["bin"]
        frequency = timedelta(days=item["frequency"])
        start_dt = (
            datetime.fromisoformat(item["binDate"].replace("Z", "+00:00"))
            .astimezone(UTC)
            .date()
        )
        end_dt = datetime.strptime(item["dtend"], "%Y%m%d").date()

        day = start_dt
        while day <= end_dt:
            if day >= today:
                entries.append(Collection(date=day, type=bin_name))
            day += frequency

    return entries


class SouthAyrshire(Scraper):
    meta = Meta(
        title="South Ayrshire Council",
        url=URL,
        lads=("S12000028",),
        cases={
            "4 Thistle Walk, Ayr, KA7 3XH": {
                "postcode": "KA7 3XH",
                "house_number": "4",
                "street": "Thistle Walk",
                "uprn": "141030966",
            },
        },
    )
    requires = frozenset({"postcode", "uprn"})
    blocker = Blocker.BOT_PROTECTION  # its site blocks Vercel's IPs (scripts/vercel_probe.py)
    transport = Transport.CURL_CFFI

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        r = await http.get(COLLECTION_PAGE_URL, timeout=30)
        page = soup(r.text)
        form = page.find("form", action=lambda action: action and "processsubmission" in action)
        if not isinstance(form, Tag) or not isinstance(form.get("action"), str):
            raise UpstreamError("South Ayrshire bin-day page has no postcode form")
        action = form["action"]
        ids = _goss_ids(action)

        r2 = await http.post(
            action,
            data={
                "BINDAYS_PAGESESSIONID": ids["page_session_id"],
                "BINDAYS_SESSIONID": ids["session_id"],
                "BINDAYS_NONCE": ids["nonce"],
                "BINDAYS_VARIABLES": "",
                "BINDAYS_PAGENAME": "PAGE1",
                "BINDAYS_PAGEINSTANCE": "0",
                "BINDAYS_PAGE1_POSTCODE": address.need("postcode"),
                "BINDAYS_FORMACTION_NEXT": "BINDAYS_PAGE1_WIZBUTTON",
            },
            headers={"Referer": COLLECTION_PAGE_URL, "Origin": URL},
            timeout=30,
        )

        page2 = soup(r2.text)
        form2 = page2.find("form", action=lambda action: action and "processsubmission" in action)
        if not isinstance(form2, Tag) or not isinstance(form2.get("action"), str):
            raise AddressNotFound(
                f"No address found for postcode {address.need('postcode')!r}. "
                "Check the postcode is correct."
            )
        action2 = form2["action"]
        ids2 = _goss_ids(action2)

        r3 = await http.post(
            action2,
            data={
                "BINDAYS_PAGESESSIONID": ids2["page_session_id"],
                "BINDAYS_SESSIONID": ids2["session_id"],
                "BINDAYS_NONCE": ids2["nonce"],
                "BINDAYS_VARIABLES": "",
                "BINDAYS_PAGENAME": "PAGE2",
                "BINDAYS_PAGEINSTANCE": "0",
                "BINDAYS_PAGE2_ADDRESSDROPDOWN": address.need("uprn"),
                "BINDAYS_FORMACTION_NEXT": "BINDAYS_PAGE2_FIELD7",
            },
            headers={"Referer": COLLECTION_PAGE_URL, "Origin": URL},
            timeout=30,
        )

        return _parse_collections(r3.text)


SCRAPER = SouthAyrshire()
