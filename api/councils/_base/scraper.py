"""The scraper contract and the harness that runs it.

A council module defines one module-level `SCRAPER`, either a `Scraper`
subclass instance (a bespoke council) or a platform class instance
configured for the council (see `api/councils/_platforms/`).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType

from api.councils._base.address import Address
from api.councils._base.collection import Collection, default_icon
from api.councils._base.errors import Blocker, InputError, NeedsBrowser
from api.councils._base.http import Http, Transport, open_http


@dataclass(frozen=True, slots=True, kw_only=True)
class Meta:
    title: str
    """The council's name: "Hartlepool Borough Council"."""
    url: str
    """The council's bin-day page, or its homepage. Used for deeplinks and the admin lookup."""
    lads: tuple[str, ...]
    """ONS LAD codes this scraper serves. Two councils sharing one service
    (Adur & Worthing) are one module listing both codes."""
    cases: Mapping[str, Mapping[str, str]] = field(default_factory=lambda: MappingProxyType({}))
    """Known-good addresses, keyed by a short name, in the frontend's param
    vocabulary: uprn, postcode, house_number, street, address, plus extras."""


class Scraper(ABC):
    """One council's bin-day lookup.

    Scrapers are stateless: one instance serves every request, so per-lookup
    state lives in `fetch`'s locals, never on `self`.
    """

    meta: Meta
    requires: frozenset[str]
    """Address fields `fetch` can't work without (`Address` field names, or
    extra param keys such as "usrn"). Keep it minimal: if you can fall back
    from the UPRN to text matching, require neither and branch in `fetch`."""
    headers: Mapping[str, str] = MappingProxyType({})
    """Sent with every request. Many councils want a browser-ish User-Agent;
    some (FixMyStreet) block a full Chrome one sent without Chrome's other
    headers, so copy what the council is known to accept."""
    transport: Transport = Transport.HTTPX
    verify_tls: bool = True
    """False only for councils serving a broken certificate chain."""
    icons: Mapping[str, str] = MappingProxyType({})
    """Icon per exact bin type, for names `default_icon` gets wrong."""
    needs_browser: str | None = None
    """Why this council can't be scraped (captcha, login), for councils that
    never work without a person at a browser. When set, `run` raises
    `NeedsBrowser` with it and makes no request; `fetch` is kept for if the
    council drops the barrier."""
    blocker: Blocker | None = None
    """With `needs_browser`, the kind of wall named in the deeplink (default
    BROWSER_ONLY). A blocked scrape is detected from the response instead
    (`Response.blocker`)."""

    @abstractmethod
    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        """Every upcoming collection the council publishes for `address`.

        Return what the council lists; the harness strips, dedupes, sorts and
        fills icons. An empty list means the council has no collections for
        this property. Raise from `errors` for anything else.
        """


class Platform[C](Scraper):
    """A shared council platform (Whitespace, Cloud9...): one class, an instance
    per council, configured by a frozen dataclass `C`."""

    config: C

    def __init__(self, meta: Meta, config: C, *, icons: Mapping[str, str] | None = None) -> None:
        self.meta = meta
        self.config = config
        if icons is not None:
            self.icons = icons


def tidy(collections: Sequence[Collection], icons: Mapping[str, str]) -> list[Collection]:
    """Whitespace-collapsed types, icons filled, duplicates dropped, sorted by date then type."""
    seen: set[tuple[object, str]] = set()
    out: list[Collection] = []
    for c in collections:
        bin_type = " ".join(c.type.split())
        if not bin_type or (c.date, bin_type) in seen:
            continue
        seen.add((c.date, bin_type))
        icon = c.icon or icons.get(bin_type) or default_icon(bin_type)
        out.append(Collection(c.date, bin_type, icon))
    out.sort(key=lambda c: (c.date, c.type))
    return out


async def run(scraper: Scraper, params: Mapping[str, object]) -> list[Collection]:
    """Run one lookup: build the `Address`, check `requires`, open `Http`, fetch, tidy.

    The caller owns the overall timeout.
    """
    if scraper.needs_browser:
        raise NeedsBrowser(scraper.needs_browser, scraper.blocker)
    address = Address.from_params(params)
    if missing := address.missing(scraper.requires):
        raise InputError(f"{scraper.meta.title} needs {', '.join(missing)}")
    async with open_http(scraper.transport, headers=scraper.headers, verify=scraper.verify_tls) as http:
        collections = await scraper.fetch(address, http)
    return tidy(collections, scraper.icons)
