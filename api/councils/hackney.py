"""Hackney: search by postcode, match the UPRN, then fetch containers and their collection dates."""

from __future__ import annotations

from datetime import date, datetime

from api.councils._base import (
    Address,
    AddressNotFound,
    Collection,
    Http,
    Meta,
    Scraper,
)

_TENANT_ID = "f806d91c-e133-43a6-ba9a-c0ae4f4cccf6"
_API_ROOT = f"https://waste-api-hackney-live.ieg4.net/{_TENANT_ID}"
_API_BASE = f"{_API_ROOT}/alloywastepages"
_KEYWORD_MAP = {
    "recycling": "Recycling",
    "food": "Food Waste",
    "garden": "Garden Waste",
    "gw_": "Garden Waste",
    "180ltr": "Refuse",
    "240ltr": "Refuse",
    "wheeled bin": "Refuse",
}


class Hackney(Scraper):
    meta = Meta(
        title="London Borough of Hackney",
        url="https://www.hackney.gov.uk/",
        lads=("E09000012",),
        cases={
            "Middleton Road": {"uprn": "100021058914", "postcode": "E8 4LL"},
            "Elrington Road": {"uprn": "100021039326", "postcode": "E8 3BJ"},
            "King Edwards Road": {"uprn": "100021051283", "postcode": "E9 7SL"},
        },
    )
    requires = frozenset({"uprn", "postcode"})
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko)",
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Origin": "https://hackney-waste-pages.azurewebsites.net",
        "Referer": "https://hackney-waste-pages.azurewebsites.net/",
    }

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        uprn = address.need("uprn")
        postcode = address.need("postcode").strip().upper()

        payload = {
            "Postcode": postcode,
            "Filters": [
                {
                    "Filter": "attributes_premisesBlpuClass",
                    "Include": True,
                    "StringMatch": "Prefix",
                    "Value": "R",
                }
            ],
        }
        response = await http.post(
            f"{_API_ROOT}/property/opensearch",
            json=payload,
            timeout=30,
        )
        data = response.json()

        address_list = data.get("addressSummaries", [])
        system_id = None
        for item in address_list:
            if isinstance(item, dict) and str(item.get("uprn")) == uprn:
                system_id = item.get("systemId")
                break

        if not system_id:
            raise AddressNotFound(f"No Hackney property found for UPRN {uprn}")

        property_response = await http.get(
            f"{_API_BASE}/getproperty/{system_id}",
            timeout=30,
        )
        property_data = property_response.json()

        container_attr = property_data.get("providerSpecificFields", {}).get(
            "attributes_wasteContainersAssignableWasteContainers", ""
        )
        if not container_attr:
            return []

        container_ids = [value.strip() for value in container_attr.split(",") if value.strip()]
        collections: list[Collection] = []

        for container_id in container_ids:
            try:
                bin_response = await http.get(
                    f"{_API_BASE}/getbin/{container_id}",
                    timeout=30,
                    check=False,
                )
                bin_data = bin_response.json()
                raw_name = bin_data.get("subTitle", "Waste")

                workflow_response = await http.get(
                    f"{_API_BASE}/getcollection/{container_id}",
                    timeout=30,
                    check=False,
                )
                workflow_data = workflow_response.json()
                workflow_ids = workflow_data.get("scheduleCodeWorkflowIDs", [])

                for workflow_id in workflow_ids:
                    dates_response = await http.get(
                        f"{_API_BASE}/getworkflow/{workflow_id}",
                        timeout=30,
                        check=False,
                    )
                    dates_json = dates_response.json()

                    raw_dates = []
                    if isinstance(dates_json, dict):
                        raw_dates = dates_json.get("trigger", {}).get("dates", [])

                    for date_str in raw_dates:
                        try:
                            collection_date = datetime.strptime(
                                date_str.split("T")[0], "%Y-%m-%d"
                            ).date()

                            if collection_date >= date.today():
                                display_name = raw_name
                                for keyword, friendly_name in _KEYWORD_MAP.items():
                                    if keyword in raw_name.lower():
                                        display_name = friendly_name
                                        break

                                collections.append(Collection(collection_date, display_name))
                        except (ValueError, TypeError, IndexError, AttributeError):
                            continue
            except (ValueError, TypeError, KeyError, IndexError, AttributeError):
                continue

        return collections


SCRAPER = Hackney()
