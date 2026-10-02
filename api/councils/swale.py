"""Swale: submit the postcode form, then the UPRN form, and parse the next two collections."""

from __future__ import annotations

import asyncio
import re
from datetime import date, timedelta
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from api.councils._base import (
    Address,
    Blocker,
    Collection,
    Http,
    InputError,
    Meta,
    NeedsBrowser,
    Response,
    Scraper,
    Transport,
    UpstreamError,
    parse_date,
    soup,
)

_TITLE = "Swale Borough Council"
_API_URL = "https://swale.gov.uk/bins-littering-and-the-environment/bins/check-your-bin-day"


def _lookup_form(page: BeautifulSoup) -> Tag | None:
    """Return the council lookup form without depending on its numeric ID."""
    for form in page.find_all("form"):
        if form.find("input", {"name": re.compile(r"^SQ_FORM_\d+_PAGE$")}):
            return form
    return None


def _field_name(form: Tag, label_text: str, fallback_tag: str | None = None) -> str:
    label = next(
        (
            item
            for item in form.find_all("label")
            if label_text in item.get_text(" ", strip=True).lower()
        ),
        None,
    )
    if label and (field_id := label.get("for")):
        field = form.find(id=field_id)
        if isinstance(field, Tag) and isinstance(field.get("name"), str):
            return field["name"]

    if fallback_tag:
        for field in form.find_all(fallback_tag, {"name": True}):
            if field.get("type") not in {"hidden", "submit"} and isinstance(field.get("name"), str):
                return field["name"]

    raise UpstreamError(f"Swale lookup form is missing its {label_text} control.")


def _submit_control(form: Tag) -> tuple[str, str]:
    control = form.find("input", {"type": "submit", "name": True, "value": True})
    if not isinstance(control, Tag):
        raise UpstreamError("Swale lookup form is missing its submit control.")
    name, value = control.get("name"), control.get("value")
    if not isinstance(name, str) or not isinstance(value, str):
        raise UpstreamError("Swale lookup form is missing its submit control.")
    return name, value


def _hidden_data(page: BeautifulSoup) -> dict[str, str]:
    # Squiz currently places its token outside the form, so collect page state.
    return {
        field["name"]: field.get("value", "")
        for field in page.select('input[type="hidden"][name]')
    }


def _raise_for_unexpected_page(page: BeautifulSoup, stage: str) -> None:
    title = page.title.get_text(" ", strip=True).lower() if page.title else ""
    content = page.get_text(" ", strip=True).lower()
    if "just a moment" in title or "challenges.cloudflare.com" in content:
        raise NeedsBrowser("Swale lookup was blocked by a Cloudflare challenge.", Blocker.BOT_PROTECTION)

    # Empty aria-live regions are always present on the results page.
    errors = [
        error
        for error in page.select(
            ".sq-form-error, .sq-form-error-message, .validation-error, "
            ".alert-danger, [role='alert']"
        )
        if error.get_text(" ", strip=True)
    ]
    if errors:
        raise InputError(f"Swale {stage} submission returned a validation error.")


async def _submit(
    http: Http, response: Response, form: Tag, payload: dict[str, str]
) -> Response:
    method_value = form.get("method", "get")
    method = method_value.lower() if isinstance(method_value, str) else "get"
    if method not in {"get", "post", "put", "patch", "delete"}:
        raise UpstreamError(f"Swale lookup form uses unsupported method {method!r}.")

    action_value = form.get("action")
    action = urljoin(response.url, action_value if isinstance(action_value, str) else response.url)
    if method == "get":
        return await http.get(action, params=payload)
    return await http.request(method.upper(), action, data=payload)  # type: ignore[arg-type]


def _collection_date(raw_text: str) -> date:
    lowered = raw_text.lower()
    today = date.today()
    if "today" in lowered:
        return today
    if "tomorrow" in lowered:
        return today + timedelta(days=1)
    date_text = lowered.split("y, ")[-1].strip()
    try:
        return parse_date(date_text)
    except ValueError as exc:
        raise UpstreamError("Swale returned an unrecognised collection date.") from exc


class Swale(Scraper):
    meta = Meta(
        title=_TITLE,
        url=_API_URL,
        lads=("E07000113",),
        cases={
            "Swale House": {"uprn": "100062375927", "postcode": "ME10 3HT"},
            "1 Harrier Drive": {"uprn": "100061091726", "postcode": "ME10 4UY"},
            "garden waste test": {"uprn": "200002536346", "postcode": "ME10 1YQ"},
        },
    )
    requires = frozenset({"uprn", "postcode"})
    transport = Transport.CURL_CFFI

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        uprn = address.need("uprn")
        postcode = address.need("postcode")

        # Load the form first so its token, cookies, and current field names are used.
        response = await http.get(_API_URL)
        page = soup(response.content)
        _raise_for_unexpected_page(page, "initial")
        form = _lookup_form(page)
        if not form:
            raise UpstreamError("Swale lookup page did not contain an input form.")

        payload = _hidden_data(page)
        payload[_field_name(form, "postcode", "input")] = postcode
        submit_name, submit_value = _submit_control(form)
        payload[submit_name] = submit_value
        response = await _submit(http, response, form, payload)
        await asyncio.sleep(5)

        page = soup(response.content)
        _raise_for_unexpected_page(page, "postcode")
        form = _lookup_form(page)
        if not form:
            raise UpstreamError("Swale postcode submission did not return an address form.")

        payload = _hidden_data(page)
        payload[_field_name(form, "address", "select")] = uprn
        submit_name, submit_value = _submit_control(form)
        payload[submit_name] = submit_value
        response = await _submit(http, response, form, payload)
        page = soup(response.content)
        _raise_for_unexpected_page(page, "UPRN")
        if _lookup_form(page):
            raise UpstreamError("Swale UPRN submission returned an input form instead of results.")

        next_date = page.find("strong", {"id": "SBC-YBD-collectionDate"})
        if not isinstance(next_date, Tag):
            raise UpstreamError("Could not find next collection date on the Swale page.")

        waste_list = page.find("div", {"id": "SBCFirstBins"})
        if not isinstance(waste_list, Tag):
            raise UpstreamError("Could not find the Swale waste list.")

        collections: list[Collection] = []
        next_day = _collection_date(next_date.get_text(" ", strip=True))
        for item in waste_list.find_all("li"):
            collections.append(
                Collection(next_day, item.get_text(strip=True))
            )

        future_collection = page.find("div", {"id": "FutureCollections"})
        if not isinstance(future_collection, Tag):
            raise UpstreamError("Could not find future collections on the Swale page.")

        future_date = future_collection.find("p")
        if not isinstance(future_date, Tag):
            raise UpstreamError("Could not find the future collection date on the Swale page.")

        future_list = page.find("ul", {"id": "FirstFutureBins"})
        if not isinstance(future_list, Tag):
            raise UpstreamError("Could not find the future bins list on the Swale page.")

        future_day = _collection_date(future_date.get_text(" ", strip=True))
        for item in future_list.find_all("li"):
            collections.append(Collection(future_day, item.get_text(strip=True)))

        remap_wastes = {
            "blue bin": "Recycling",
            "food waste": "Food",
            "green bin": "Refuse",
            "garden waste": "Garden",
        }
        entries: list[Collection] = []
        for collection in collections:
            waste_type = remap_wastes.get(collection.type.strip().lower())
            if waste_type is not None:
                entries.append(Collection(collection.date, waste_type))
        return entries


SCRAPER = Swale()
