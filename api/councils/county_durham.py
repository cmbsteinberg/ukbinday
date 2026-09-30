"""Durham: sends a UPRN to its JSON-RPC calendar endpoint and parses returned jobs."""

from __future__ import annotations

import json
import re
from datetime import date, datetime

from api.councils._base import Address, Collection, Http, Meta, Scraper

_API_URL = "https://www.durham.gov.uk/apiserver/ajaxlibrary/"

_NAME_MAP = {
    "Empty Bin Refuse": "Rubbish bin",
    "Empty Bin Recycling": "Recycle bin",
    "Empty Bin Organic": "Garden waste bin",
    "Empty Bin Food": "Food waste bin",
    "Empty Bin Clinical": "Clinical Waste",
}


def _map_bin_name(name: str) -> str:
    for prefix, display in _NAME_MAP.items():
        if name.startswith(prefix):
            return display
    return name


class CountyDurham(Scraper):
    meta = Meta(
        title="Durham County Council",
        url="https://durham.gov.uk",
        lads=("E06000047",),
        cases={
            "Test_001": {"uprn": "100110414978"},
            "Test_002": {"uprn": "100110427200"},
        },
    )
    requires = frozenset({"uprn"})

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        uprn = address.need("uprn")
        payload = json.dumps(
            {
                "jsonrpc": "2.0",
                "method": "durham.Localities.GetBartecCalendar",
                "params": {"uprn": uprn},
                "id": "21",
                "name": "V2 AJAX End Point Library Worker",
            }
        )
        response = await http.post(
            _API_URL,
            content=payload,
            headers={
                "Content-Type": "application/json",
                "Referer": f"https://www.durham.gov.uk/bincollections?uprn={uprn}",
            },
        )

        xml_str = response.json().get("result", "")
        today = date.today()
        collections: list[Collection] = []

        for match in re.finditer(r"<Job>(.*?)</Job>", xml_str, re.DOTALL):
            job_xml = match.group(1)
            name_match = re.search(r"<Name[^>]*>([^<]+)</Name>", job_xml)
            sched_match = re.search(
                r"<ScheduledStart>([^<]+)</ScheduledStart>", job_xml
            )
            if not name_match or not sched_match:
                continue

            name = name_match.group(1).strip()
            sched_str = sched_match.group(1).strip()
            try:
                collection_date = datetime.fromisoformat(sched_str).date()
            except ValueError:
                continue

            if collection_date < today:
                continue

            collections.append(Collection(collection_date, _map_bin_name(name)))

        return collections


SCRAPER = CountyDurham()
