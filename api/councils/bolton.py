"""Bolton: search properties by postcode, select the matching address, then fetch its bin schedule."""

from __future__ import annotations

from datetime import datetime, timedelta

from api.councils._base import (
    Address,
    AddressNotFound,
    Collection,
    Http,
    Meta,
    Scraper,
    match_address,
    soup,
    text_of,
)

AUTH_KEY = "Authorization"
API_NAME = "es_bin_collection_dates"
API_BASE = "https://bolton.form.uk.empro.verintcloudservices.com/"
API_URLS = {
    "authentication": "api/citizen?archived=Y&preview=false&locale=en",
    "postcode_lookup": "api/widget?action=propertysearch&actionedby=ps_address&loadform=true&access=citizen&locale=en",
    "set_object": "api/setobjectid?objecttype=property&objectid={uprn}&loaddata=true",
    "collection_dates": "api/custom?action=es_get_bin_collection_dates&actionedby=uprn_changed&loadform=true&access=citizen&locale=en",
}


def _get_headers(auth_token: str) -> dict[str, str]:
    return {
        "referer": API_BASE,
        "accept": "application/json",
        "content-type": "application/json",
        "user-agent": "Mozilla/5.0",
        AUTH_KEY: auth_token,
    }


def _create_payload(data: dict[str, str]) -> dict[str, object]:
    return {
        "name": API_NAME,
        "email": "",
        "caseid": "",
        "xref": "",
        "xref1": "",
        "xref2": "",
        "data": data,
    }


def _parse_html(html_content: str) -> list[Collection]:
    entries: list[Collection] = []
    page = soup(html_content)

    bin_sections = page.find_all(
        "div", style=lambda value: value and "overflow:auto" in value
    )

    for section in bin_sections:
        bin_type = text_of(section.find("strong")).replace(":", "").strip()
        if "caddy" in bin_type.lower():
            bin_type = "Food container"
        else:
            for colour in ["Grey", "Beige", "Burgundy", "Green", "Garden"]:
                if colour.lower() in bin_type.lower():
                    bin_type = f"{colour} Bin"
                    break

        for date_item in section.find_all("li"):
            date_text = text_of(date_item)
            try:
                date_obj = datetime.strptime(date_text, "%A %d %B %Y").date()
            except ValueError:
                continue
            entries.append(Collection(date_obj, bin_type))

    return entries


class Bolton(Scraper):
    meta = Meta(
        title="Bolton Council",
        url="https://www.bolton.gov.uk",
        lads=("E08000001",),
        cases={
            "Test_Postcode_Without_Space": {"postcode": "BL52AX", "house_number": "13"},
            "Test_Postcode_With_Space": {"postcode": "BL1 5BQ", "house_number": "14"},
            "Test_House_With_Street_Before_Number": {
                "postcode": "BL1 5XR",
                "house_number": "WOODSLEIGH COPPICE 2",
            },
        },
    )
    requires = frozenset({"postcode", "house_number"})

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        token_response = await http.get(API_BASE + API_URLS["authentication"])
        auth_token = token_response.headers[AUTH_KEY]

        addresses_response = await http.post(
            API_BASE + API_URLS["postcode_lookup"],
            headers=_get_headers(auth_token),
            json=_create_payload({"postcode": address.need("postcode")}),
        )
        addresses_data = addresses_response.json()
        candidates = addresses_data["data"]
        if not candidates:
            raise AddressNotFound(f"No properties for postcode {address.postcode}")

        if AUTH_KEY in addresses_response.headers:
            auth_token = addresses_response.headers[AUTH_KEY]

        selected = match_address(
            address,
            candidates,
            text=lambda candidate: candidate["label"],
            uprn=lambda candidate: candidate["value"],
        )
        uprn = selected["value"]

        set_object_response = await http.post(
            (API_BASE + API_URLS["set_object"]).format(uprn=uprn),
            headers=_get_headers(auth_token),
        )
        set_object_data = set_object_response.json()
        canonical_uprn = set_object_data["profileData"]["property-UPRN"]

        if AUTH_KEY in set_object_response.headers:
            auth_token = set_object_response.headers[AUTH_KEY]

        post_data = _create_payload(
            {
                "uprn": canonical_uprn,
                "start_date": (datetime.now() - timedelta(days=1)).strftime("%d/%m/%Y"),
                "end_date": (datetime.now() + timedelta(days=365)).strftime("%d/%m/%Y"),
            }
        )

        schedule = await http.post(
            API_BASE + API_URLS["collection_dates"],
            json=post_data,
            headers=_get_headers(auth_token),
        )
        result = schedule.json()
        return _parse_html(result["data"]["collection_dates"])


SCRAPER = Bolton()
