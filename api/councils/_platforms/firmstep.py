"""Firmstep Self-Service (`selfservice.<council>.gov.uk/renderform`).

The councils on it share form plumbing but not a flow, so this module holds
the shared steps as functions, plus one `Scraper` for the councils that submit
a single form with an address id:

- `hidden_inputs` / `verification_token`: GET the form page and read its hidden
  fields (anti-forgery token, FormGuid, ObjectTemplateID, CurrentSectionID).
- `lookup_addresses`: POST `core/addresslookup` with a postcode and get back
  `{address key: label}`; keys are "U" + UPRN.
- `FirmstepAddressForm`: GET the form, POST it with the address key in the
  council's address field, parse the results page. If nothing comes back and the
  id was a postcode, look the postcode up and resubmit with its first address.

Broxtowe and Rushcliffe each have their own form flow (different fields, a
different results page) and only use the functions. A config-driven
`Scraper` for all four would be mostly per-council parsing callbacks.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from bs4 import BeautifulSoup, Tag

from api.councils._base import (
    Address,
    Collection,
    Http,
    InputError,
    Meta,
    Scraper,
    UpstreamError,
    soup,
)

TIMEOUT = 30
_REQUIRED_INPUTS = frozenset({"__RequestVerificationToken", "FormGuid", "ObjectTemplateID", "CurrentSectionID"})


async def hidden_inputs(http: Http, form_url: str) -> dict[str, str]:
    """Every named hidden input on the form page."""
    r = await http.get(form_url, timeout=TIMEOUT)
    return {
        str(inp["name"]): str(inp.get("value", ""))
        for inp in soup(r.text).find_all("input", type="hidden")
        if isinstance(inp, Tag) and inp.get("name")
    }


async def verification_token(http: Http, form_url: str) -> str:
    token = (await hidden_inputs(http, form_url)).get("__RequestVerificationToken")
    if not token:
        raise UpstreamError(f"__RequestVerificationToken not found in form response from {form_url}")
    return token


async def lookup_addresses(http: Http, lookup_url: str, postcode: str, *, search_nlpg: str = "True") -> dict[str, str]:
    """`{address key: label}` for a postcode."""
    r = await http.post(
        lookup_url,
        data={"query": postcode, "searchNlpg": search_nlpg, "classification": ""},
        timeout=TIMEOUT,
    )
    raw = r.json()
    if isinstance(raw, dict):
        return {str(k): str(v) for k, v in raw.items()}
    if isinstance(raw, list):
        return {
            str(item["Key"]): str(item["Value"]) for item in raw if isinstance(item, dict) and "Key" in item and "Value" in item
        }
    return {}


@dataclass(frozen=True, slots=True, kw_only=True)
class FirmstepAddressFormConfig:
    form_url: str
    render_url: str
    lookup_url: str
    address_field: str
    """The form field holding the address key: "FF2924"."""
    parse: Callable[[BeautifulSoup], list[Collection]]
    """Collections from the results page."""
    field_suffixes: Mapping[str, str] = field(default_factory=lambda: MappingProxyType({}))
    """Extra fields named `address_field + suffix`: {"lbltxt": "Collection Address"}."""
    search_nlpg: str = "True"
    """`searchNlpg` for the postcode-lookup fallback."""


class FirmstepAddressForm(Scraper):
    """Councils that take the address key ("U" + UPRN, or a postcode) directly."""

    requires = frozenset()

    def __init__(self, meta: Meta, config: FirmstepAddressFormConfig, *, icons: Mapping[str, str] | None = None) -> None:
        self.meta = meta
        self.config = config
        if icons is not None:
            self.icons = icons

    async def _submit(self, http: Http, address_id: str) -> list[Collection]:
        cfg = self.config
        inputs = await hidden_inputs(http, cfg.form_url)
        if not _REQUIRED_INPUTS.issubset(inputs):
            raise UpstreamError(f"Unable to read the form metadata at {cfg.form_url}")
        payload = {
            "__RequestVerificationToken": inputs["__RequestVerificationToken"],
            "FormGuid": inputs["FormGuid"],
            "ObjectTemplateID": inputs["ObjectTemplateID"],
            "Trigger": "submit",
            "CurrentSectionID": inputs["CurrentSectionID"],
            cfg.address_field: address_id,
            **{cfg.address_field + suffix: value for suffix, value in cfg.field_suffixes.items()},
        }
        r = await http.post(cfg.render_url, data=payload, timeout=TIMEOUT)
        return cfg.parse(soup(r.text))

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        address_id = address.extra.get("address_id") or (f"U{address.uprn}" if address.uprn else address.postcode)
        if not address_id:
            raise InputError("A UPRN or postcode is required")
        collections = await self._submit(http, address_id)
        if not collections and not address_id.startswith("U"):
            addresses = await lookup_addresses(
                http, self.config.lookup_url, address_id, search_nlpg=self.config.search_nlpg
            )
            if addresses:
                collections = await self._submit(http, next(iter(addresses)))
        return collections
