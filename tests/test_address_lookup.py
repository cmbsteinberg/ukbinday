"""
Unit tests for the address-line splitter (no network calls, fast).

_split_address_line_1 turns Placecube addressLine1/line2 into the
(house_number_or_name, street) pair the frontend sends to scrapers.
Flats with building names previously passed through un-split (or
mis-split), which made Whitespace-portal councils such as Mid Sussex
return zero address matches → HTTP 422. See RH16 1LG (Harlands House).

Usage:
    uv run pytest tests/test_address_lookup.py -v
"""

import pytest

from api.services.address_lookup import _split_address_line_1

pytestmark = pytest.mark.ci


@pytest.mark.parametrize(
    ("line1", "line2", "expected"),
    [
        # --- pre-existing behaviour (must not regress) ---
        ("23 High Street", "Lindfield", ("23", "High Street")),
        ("23 HIGH STREET", None, ("23", "High Street")),
        ("Hapstead Hall", "High Street", ("Hapstead Hall", "High Street")),
        ("Muster Court", "Boltro Road", ("Muster Court", "Boltro Road")),
        (None, "Boltro Road", (None, "Boltro Road")),
        (None, None, (None, None)),
        # --- flats: drop the building name, keep the flat + real street ---
        (
            "Flat 55, Harlands House",
            "Harlands Road",
            ("Flat 55", "Harlands Road"),
        ),
        (
            "Flat 55 Harlands House",
            "Harlands Road",
            ("Flat 55", "Harlands Road"),
        ),
        ("Flat 55", "Harlands Road", ("Flat 55", "Harlands Road")),
        ("FLAT 55, HARLANDS HOUSE", "HARLANDS ROAD", ("Flat 55", "Harlands Road")),
        ("flat 5a, Some House", "Some Road", ("Flat 5a", "Some Road")),
        ("Apartment 3, Harlands House", "Harlands Road", ("Apartment 3", "Harlands Road")),
        ("Unit 4, Harlands House", "Harlands Road", ("Unit 4", "Harlands Road")),
        # flat with no line2 falls back to the remainder as street
        ("Flat 55, Harlands House", None, ("Flat 55", "Harlands House")),
        # --- number + building in line1, real street in line2 ---
        ("55 Harlands House", "Harlands Road", ("55", "Harlands Road")),
        # street already in line1 + locality in line2: unchanged behaviour
        ("23 High Street", "Haywards Heath", ("23", "High Street")),
        # --- sub-building taxonomy (uk_address_matcher): letter flats,
        # floor descriptors, rooms and multi-word dwelling types ---
        ("Flat A, Example Court", "Demo Road", ("Flat A", "Demo Road")),
        (
            "Ground Floor Flat 2, Elm House",
            "Elm Road",
            ("Ground Floor Flat 2", "Elm Road"),
        ),
        (
            "Basement Flat 1, Rose Villa",
            "Rose Road",
            ("Basement Flat 1", "Rose Road"),
        ),
        ("Room 5", "18 Aylsham Road", ("18 Room 5", "18 Aylsham Road")),
        # bare sub-unit of a numbered building leads with the building
        # number (portals list building-first: "18, ROOM 5, ...")
        ("Flat 5", "10 Demo Road", ("10 Flat 5", "10 Demo Road")),
        ("Unit 5", "10 Demo Road", ("10 Unit 5", "10 Demo Road")),
        (
            "Basement Flat",
            "10 Demo Road",
            ("10 Basement Flat", "10 Demo Road"),
        ),
        (
            "Studio Apartment 7, Park View",
            "Park Road",
            ("Studio Apartment 7", "Park Road"),
        ),
        # --- guards: bare names fall through untouched ---
        ("Flat", "High Street", ("Flat", "High Street")),
        ("Flat Fish", "High Street", ("Flat Fish", "High Street")),
    ],
    ids=[
        "house-number-and-street",
        "uppercase-line1-only",
        "named-property",
        "named-building-with-street-line2",
        "empty-line1",
        "both-empty",
        "flat-with-building-comma",
        "flat-with-building-no-comma",
        "flat-only",
        "flat-uppercase",
        "flat-lowercase-alphanum",
        "apartment-with-building",
        "unit-with-building",
        "flat-no-line2-fallback",
        "number-building-plus-street-line2",
        "street-in-line1-locality-line2",
        "letter-flat-with-building",
        "floor-flat-with-building",
        "basement-flat-with-building",
        "room-with-street-line2",
        "bare-flat-in-numbered-building",
        "bare-unit-in-numbered-building",
        "bare-basement-flat-in-numbered-building",
        "studio-apartment-with-building",
        "bare-flat-passes-through",
        "flat-named-shop-passes-through",
    ],
)
def test_split_address_line_1(line1, line2, expected):
    assert _split_address_line_1(line1, line2) == expected
