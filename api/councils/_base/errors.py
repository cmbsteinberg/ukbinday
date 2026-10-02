"""What a scraper may raise. Anything else escaping `fetch` is a bug in the scraper.

The orchestrator maps these to HTTP answers:

- `InputError` (and `AddressNotFound`): 422, the council rejects what we sent.
- `UpstreamError`: 503, the council site is down, erroring or blocking us.
- `NeedsBrowser`: a deeplink to the council's own page (captcha, JS-only, login),
  with the `Blocker` that says why.

`Http` raises `UpstreamError` itself for transport failures and 4xx/5xx
responses, so scrapers never see backend-specific exception types.
"""

from __future__ import annotations

from collections.abc import Sequence
from enum import StrEnum


class Blocker(StrEnum):
    """Why a council answers with a link to its own site instead of bin days.

    Public: deeplinks carry it as `blocker`, with `label` as `blocker_label`."""

    CAPTCHA = "captcha"
    LOGIN = "login"
    BOT_PROTECTION = "bot_protection"
    BROWSER_ONLY = "browser_only"
    NO_LOOKUP = "no_lookup"
    SITE_DOWN = "site_down"
    NOT_SUPPORTED = "not_supported"

    @property
    def label(self) -> str:
        return _BLOCKER_LABELS[self]


_BLOCKER_LABELS = {
    Blocker.CAPTCHA: "Requires a captcha",
    Blocker.LOGIN: "Requires a council account login",
    Blocker.BOT_PROTECTION: "Blocks automated lookups",
    Blocker.BROWSER_ONLY: "Only works in a web browser",
    Blocker.NO_LOOKUP: "No online address lookup",
    Blocker.SITE_DOWN: "Website not responding",
    Blocker.NOT_SUPPORTED: "Not supported yet",
}


class ScraperError(Exception):
    """Base for every error a scraper raises on purpose."""


class InputError(ScraperError):
    """The council rejected the address details we sent (unknown UPRN, bad postcode)."""


class AddressNotFound(InputError):
    """No property on the council's list matches the address.

    `suggestions` carries the council's own labels when the site offered a list,
    so the caller can show the user what the council knows about their postcode.
    """

    def __init__(self, message: str, suggestions: Sequence[str] = ()) -> None:
        super().__init__(message)
        self.suggestions = tuple(suggestions)


class UpstreamError(ScraperError):
    """The council's site failed: unreachable, timed out, HTTP error, or blocked us.

    `blocker` is BOT_PROTECTION when the site answered with a bot wall
    (`Response` detects it), else None."""

    def __init__(self, message: str, blocker: Blocker | None = None) -> None:
        super().__init__(message)
        self.blocker = blocker


class NeedsBrowser(ScraperError):
    """The council's service can't be scraped without a person at a browser."""

    def __init__(self, message: str, blocker: Blocker | None = None) -> None:
        super().__init__(message)
        self.blocker = blocker
