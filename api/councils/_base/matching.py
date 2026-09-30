"""Pick the user's property out of a council's address list."""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable

from api.councils._base.address import Address, normalise_uprn
from api.councils._base.errors import AddressNotFound


def normalise_text(text: str) -> str:
    """Lower case, punctuation to spaces, whitespace collapsed: "Flat 2, 47a Main St." -> "flat 2 47a main st"."""
    return " ".join(re.sub(r"[^\w]+", " ", text.lower()).split())


def _has_phrase(haystack: str, phrase: str) -> bool:
    """Whole-token containment: "6" is in "6 main st" but not in "56 main st" or "6a main st"."""
    return f" {phrase} " in f" {haystack} "


def match_address[T](
    address: Address,
    candidates: Iterable[T],
    *,
    text: Callable[[T], str],
    uprn: Callable[[T], object] | None = None,
) -> T:
    """Return the candidate that is the user's property.

    Tries, in order, and returns the first tier with a hit:

    1. UPRN equality (leading zeros ignored), when both sides have one.
    2. The candidate text starts with `address.first_line` ("47 Montagu Avenue").
    3. The house number and the street both appear as whole words.
    4. The house number alone is the candidate's first word (for councils
       whose list omits the street because the postcode already fixes it).

    Within a tier the shortest text wins, so "47 Montagu Avenue" beats
    "Flat 2, 47 Montagu Avenue". Raises `AddressNotFound` with the council's
    labels as suggestions when nothing matches.
    """
    pool = list(candidates)
    labels = [text(c) for c in pool]
    if not pool:
        raise AddressNotFound(f"The council lists no addresses for {address.postcode or address.label}")

    if uprn is not None and address.uprn:
        for candidate in pool:
            if normalise_uprn(uprn(candidate)) == address.uprn:
                return candidate

    texts = [normalise_text(label) for label in labels]
    number = normalise_text(address.house_number or "")
    street = normalise_text(address.street or "")
    first_line = normalise_text(address.first_line or "")

    tiers: list[Callable[[str], bool]] = []
    if first_line:
        tiers.append(lambda t: t == first_line or t.startswith(first_line + " "))
    if number and street:
        tiers.append(lambda t: _has_phrase(t, number) and _has_phrase(t, street))
    if number:
        tiers.append(lambda t: t == number or t.startswith(number + " "))

    for tier in tiers:
        hits = [i for i, t in enumerate(texts) if tier(t)]
        if hits:
            return pool[min(hits, key=lambda i: len(texts[i]))]

    wanted = address.first_line or address.label or address.uprn or "the address"
    raise AddressNotFound(f"No property matching {wanted!r} on the council's list", labels)
