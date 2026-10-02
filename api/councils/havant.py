"""Havant: logs in with council credentials and reads collection events from the home page."""

from __future__ import annotations

import datetime
import json
import re

from api.councils._base import (
    Address,
    Blocker,
    Collection,
    Http,
    InputError,
    Meta,
    Scraper,
    UpstreamError,
    soup,
)

_URL = "https://waste.havant.gov.uk"
_EVENTS_REGEX = re.compile(r"eventSettings.*?dataSource.*?isJson\((\[.*?\])\)", re.DOTALL)


class Havant(Scraper):
    meta = Meta(
        title="Havant Borough Council",
        url=_URL,
        lads=("E07000090",),
        cases={},
    )
    requires = frozenset({"username", "password"})
    needs_browser = "Havant's bin days are only shown after logging in to a council account."
    blocker = Blocker.LOGIN

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        username = address.need("username")
        password = address.need("password")

        login_url = f"{_URL}/Identity/Account/Login"
        response = await http.get(login_url)
        token_element = soup(response.text).find(
            "input", attrs={"name": "__RequestVerificationToken"}
        )
        if token_element is None:
            raise UpstreamError("Unable to find anti-forgery token")
        token = token_element.get("value")
        if not token:
            raise UpstreamError("Unable to find anti-forgery token")

        login_payload = {
            "Input.Email": username,
            "Input.Password": password,
            "__RequestVerificationToken": token,
            "Input.RememberMe": "false",
        }
        response = await http.post(login_url, data=login_payload)
        if "/Identity/Account/Login" in response.url:
            raise InputError("Login failed. Please check your username and password.")

        response = await http.get(_URL)
        matches = _EVENTS_REGEX.search(response.text)
        if not matches:
            raise UpstreamError("Could not find collection data in the page")
        events_json = json.loads(matches.group(1))

        collections = []
        for event in events_json:
            if event.get("AppointmentType") != "Job":
                continue
            day = datetime.datetime.strptime(
                event["StartTime"], "%Y-%m-%dT%H:%M:%S"
            ).date()
            waste_type = event["Subject"].strip()
            collections.append(Collection(day, waste_type))
        return collections


SCRAPER = Havant()
