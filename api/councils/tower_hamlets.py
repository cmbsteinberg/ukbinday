"""Tower Hamlets: an AchieveForms lookup keyed on the UPRN, returning collection dates."""

from __future__ import annotations

import base64
import datetime
import json
import re
import urllib.parse

from api.councils._base import (
    Address,
    Collection,
    Http,
    Meta,
    Scraper,
    UpstreamError,
)

_BASE_URL = "https://towerhamlets-self.achieveservice.com"
_SERVICE_PATH = "/service/Check_your_waste_and_recycling_collection_days"

_FALLBACK_LOOKUP = "654ba9e6a9886"
_FALLBACK_FORM = "AF-Form-968b261c-ffa8-4368-9f00-5fe7e879d5b9"
_FALLBACK_STAGE = "AF-Stage-4c6e80ac-7dc2-46e4-afa6-fd46d11565ec"

_ALLOWED_SERVICES = frozenset(
    {
        "General Waste",
        "Recycling",
        "Food/Garden Waste",
        "Food Waste",
        "Garden Waste",
    }
)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,"
        "webp,image/apng,*/*;q=0.8"
    ),
}


class TowerHamlets(Scraper):
    meta = Meta(
        title="London Borough of Tower Hamlets",
        url="https://www.towerhamlets.gov.uk/",
        lads=("E09000030",),
        cases={
            "Celtic St": {"uprn": "6085613"},
            "Ernest St": {"uprn": "6034631"},
            "Blue Anchor Yard": {"uprn": "6007545"},
        },
    )
    requires = frozenset({"uprn"})
    headers = _HEADERS

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        uprn = address.need("uprn")

        response = await http.get(
            f"{_BASE_URL}{_SERVICE_PATH}",
            timeout=30,
        )
        html_content = response.text

        sid_match = re.search(
            r'["\']auth-session["\']\s*:\s*["\']([^"\']+)["\']',
            html_content,
        )
        uri_match = re.search(
            r'["\']publish-uri["\']\s*:\s*["\']([^"\']+)["\']',
            html_content,
        )
        if not sid_match or not uri_match:
            raise UpstreamError(
                "Handshake failed: Could not find auth-session or publish-uri."
            )

        sid = sid_match.group(1)
        stage_uri = urllib.parse.unquote(uri_match.group(1)).replace("\\/", "/")

        try:
            stage_response = await http.get(
                f"{_BASE_URL}/api/get-document/json",
                params={"uri": stage_uri, "sid": sid},
            )
            stage_data = stage_response.json()

            metadata = {
                item["Name"]: item["Value"]
                for item in stage_data.get("data", {}).get("metadata", [])
            }
            form_id = metadata.get("form-id", _FALLBACK_FORM)
            stage_id = metadata.get("stage-id", _FALLBACK_STAGE)

            encoded_content = stage_data.get("data", {}).get("content", "")
            decoded_content = json.loads(
                base64.b64decode(encoded_content).decode("utf-8")
            )

            lookup_id = None
            for section in decoded_content.get("sections", []):
                for field in section.get("fields", []):
                    if field.get("props", {}).get("dataName") == "collectionDates":
                        lookup_id = field.get("props", {}).get("lookup")
                        break
            lookup_id = lookup_id or _FALLBACK_LOOKUP
        except (UpstreamError, ValueError, KeyError):
            form_id, stage_id, lookup_id = (
                _FALLBACK_FORM,
                _FALLBACK_STAGE,
                _FALLBACK_LOOKUP,
            )

        token_response = await http.get(
            f"{_BASE_URL}/api/nextref",
            params={"sid": sid},
            timeout=30,
        )
        csrf = token_response.json()["data"]["csrfToken"]

        now_str = datetime.datetime.now().strftime("%Y-%m-%d")
        payload = {
            "stopOnFailure": True,
            "usePHPIntegrations": True,
            "stage_id": stage_id,
            "stage_name": "Stage 1",
            "formId": form_id,
            "formValues": {
                "Section 2": {
                    "howCheck": {"value": "property"},
                    "NextCollectionFromDate": {"value": now_str},
                    "addressDetails": {
                        "value": {"Section 1": {"Address": {"value": uprn}}}
                    },
                    "AccountSiteUPRN": {"value": uprn},
                    "TH_uprn": {"value": uprn},
                }
            },
        }

        result = await http.post(
            f"{_BASE_URL}/apibroker/runLookup",
            params={
                "id": lookup_id,
                "sid": sid,
                "noRetry": "false",
                "app_name": "AF-Renderer::Self",
            },
            json=payload,
            headers={"X-CSRF-Token": csrf},
            timeout=30,
        )
        data = result.json()

        integration = data.get("integration", {}).get("transformed", {})
        if integration.get("error"):
            raise UpstreamError(f"Council API Error: {integration.get('error')}")

        rows_data = integration.get("rows_data", {})
        rows = rows_data.values() if isinstance(rows_data, dict) else rows_data
        if not rows:
            return []

        collections: list[Collection] = []
        today = datetime.date.today()
        for row in rows:
            service = row.get("CollectionService")
            date_str = row.get("CollectionDate")
            if not service or not date_str or service not in _ALLOWED_SERVICES:
                continue
            try:
                collection_date = datetime.datetime.strptime(
                    f"{date_str} {today.year}", "%d %B %Y"
                ).date()
                if collection_date < today - datetime.timedelta(days=31):
                    collection_date = collection_date.replace(year=today.year + 1)
                collections.append(Collection(collection_date, service))
            except ValueError:
                continue

        return collections


SCRAPER = TowerHamlets()
