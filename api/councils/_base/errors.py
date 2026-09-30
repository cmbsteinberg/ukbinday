"""What a scraper may raise. Anything else escaping `fetch` is a bug in the scraper.

The orchestrator maps these to HTTP answers:

- `InputError` (and `AddressNotFound`): 422, the council rejects what we sent.
- `UpstreamError`: 503, the council site is down, erroring or blocking us.
- `NeedsBrowser`: a deeplink to the council's own page (captcha, JS-only, login).

`Http` raises `UpstreamError` itself for transport failures and 4xx/5xx
responses, so scrapers never see backend-specific exception types.
"""

from __future__ import annotations

from collections.abc import Sequence


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
    """The council's site failed: unreachable, timed out, HTTP error, or blocked us."""


class NeedsBrowser(ScraperError):
    """The council's service can't be scraped without a person at a browser."""
