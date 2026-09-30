"""The framework every council module is written against. Import from here."""

from api.councils._base.address import Address, Field
from api.councils._base.collection import Collection, Icon, default_icon
from api.councils._base.dates import every, next_weekday, parse_date, weekday_number
from api.councils._base.errors import (
    AddressNotFound,
    InputError,
    NeedsBrowser,
    ScraperError,
    UpstreamError,
)
from api.councils._base.html import soup, text_of
from api.councils._base.http import Http, Response, Transport
from api.councils._base.ics import IcsEvent, parse_ics
from api.councils._base.matching import match_address, normalise_text
from api.councils._base.scraper import Meta, Scraper, run

__all__ = [
    "Address",
    "AddressNotFound",
    "Collection",
    "Field",
    "Http",
    "Icon",
    "IcsEvent",
    "InputError",
    "Meta",
    "NeedsBrowser",
    "Response",
    "Scraper",
    "ScraperError",
    "Transport",
    "UpstreamError",
    "default_icon",
    "every",
    "match_address",
    "next_weekday",
    "normalise_text",
    "parse_date",
    "parse_ics",
    "run",
    "soup",
    "text_of",
    "weekday_number",
]
