"""The address a scraper is asked about, built once from the request's query params.

`Address.from_params` is the only code that knows the frontend's param format.
Scrapers read typed fields and never parse the query string or the joined label.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Literal

from api.councils._base.errors import InputError

# Fields the frontend sends for every lookup. Anything else a scraper needs
# (usrn, property_id...) arrives in `Address.extra` and is named in `requires`
# by its param key.
Field = Literal["uprn", "postcode", "house_number", "street", "label"]
FIELDS: frozenset[str] = frozenset(Field.__args__)

# Query keys that aren't address data.
_NOT_ADDRESS = frozenset({"council"})


def _clean(value: object) -> str | None:
    if value is None:
        return None
    text = " ".join(str(value).split())
    return text or None


def normalise_uprn(value: object) -> str | None:
    """Digits only, leading zeros stripped. None for a missing or all-zero placeholder."""
    text = _clean(value)
    if text is None or not text.isdigit():
        return None
    return text.lstrip("0") or None


def normalise_postcode(value: object) -> str | None:
    """Upper case with the single space before the inward code: "NE3 4JJ"."""
    text = _clean(value)
    if text is None:
        return None
    compact = re.sub(r"\s+", "", text).upper()
    if len(compact) < 5:
        return compact
    return f"{compact[:-3]} {compact[-3:]}"


@dataclass(frozen=True, slots=True, kw_only=True)
class Address:
    uprn: str | None = None
    """Digits only, no leading zeros. Pad it yourself if the council wants 12 digits."""
    postcode: str | None = None
    """Normalised: "NE3 4JJ"."""
    house_number: str | None = None
    """The primary addressable object as the address API gives it: "47", "47A", "Flat 2", "Rose Cottage"."""
    street: str | None = None
    label: str | None = None
    """The frontend's full display string: "47, Montagu Avenue, Newcastle Upon Tyne, NE3 4JJ"."""
    extra: Mapping[str, str] = field(default_factory=lambda: MappingProxyType({}))
    """Council-specific keys (usrn, property_id, calendar_number...)."""

    @classmethod
    def from_params(cls, params: Mapping[str, object]) -> Address:
        """Build from the /lookup query params (plus `uprn` from the path).

        The frontend sends `address` for the joined label; it lands in `label`.
        """
        known = {"uprn", "postcode", "house_number", "street", "address"}
        extra = {
            key: text
            for key, value in params.items()
            if key not in known and key not in _NOT_ADDRESS
            and (text := _clean(value)) is not None
        }
        return cls(
            uprn=normalise_uprn(params.get("uprn")),
            postcode=normalise_postcode(params.get("postcode")),
            house_number=_clean(params.get("house_number")),
            street=_clean(params.get("street")),
            label=_clean(params.get("address")),
            extra=MappingProxyType(extra),
        )

    def get(self, name: str) -> str | None:
        """A field or extra key by name, None when absent."""
        if name in FIELDS:
            return getattr(self, name)
        return self.extra.get(name)

    def need(self, name: Field | str) -> str:
        """A value the scraper can't work without, typed as `str`.

        Name it in the scraper's `requires` too: the harness checks those before
        `fetch` runs, so this only raises when a scraper reads something it
        didn't declare.
        """
        value = self.get(name)
        if value is None:
            raise InputError(f"{name} is required")
        return value

    def missing(self, names: frozenset[str]) -> list[str]:
        return sorted(name for name in names if self.get(name) is None)

    @property
    def first_line(self) -> str | None:
        """"47 Montagu Avenue": house number and street, else the label's first part."""
        if self.house_number and self.street:
            if self.street.lower().startswith(self.house_number.lower() + " "):
                return self.street
            return f"{self.house_number} {self.street}"
        if self.label:
            parts = [p.strip() for p in self.label.split(",") if p.strip()]
            if len(parts) >= 2 and parts[0][:1].isdigit() and not parts[1][:1].isdigit():
                return f"{parts[0]} {parts[1]}"
            if parts:
                return parts[0]
        return self.house_number or self.street

    @property
    def postcode_compact(self) -> str | None:
        """"NE34JJ"."""
        return self.postcode.replace(" ", "") if self.postcode else None
