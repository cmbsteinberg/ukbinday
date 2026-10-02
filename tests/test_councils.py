"""Smoke tests for api/councils/: every module loads and the LAD claims are sound."""

from __future__ import annotations

from datetime import date

import pytest

from api.councils._base import (
    Address,
    Collection,
    Icon,
    Scraper,
    colour_of,
    match_address,
    parse_date,
)
from api.councils._base.discovery import by_lad, load, module_names
from api.councils._base.scraper import tidy

pytestmark = pytest.mark.ci

MODULES = module_names()


@pytest.mark.parametrize("name", MODULES)
def test_module_loads(name: str) -> None:
    scraper = load(name)
    assert isinstance(scraper, Scraper)
    assert scraper.meta.lads, f"{name} serves no LADs"
    assert isinstance(scraper.requires, frozenset)
    for case in scraper.meta.cases.values():
        assert all(isinstance(v, str) for v in case.values()), f"{name} case values must be strings"


def test_lad_claims_unique_and_known() -> None:
    by_lad({name: load(name) for name in MODULES})


def test_address_from_params() -> None:
    a = Address.from_params(
        {"uprn": "010014355477", "postcode": "ne34jj", "house_number": " 47 ", "street": "Montagu Avenue",
         "address": "47, Montagu Avenue, Newcastle Upon Tyne, NE3 4JJ", "council": "x", "usrn": "123"}
    )
    assert (a.uprn, a.postcode, a.first_line, a.postcode_compact) == ("10014355477", "NE3 4JJ", "47 Montagu Avenue", "NE34JJ")
    assert a.extra == {"usrn": "123"}
    assert Address.from_params({"uprn": "0"}).uprn is None


def test_match_address_tiers() -> None:
    options = ["Flat 2, 47 Montagu Avenue, NE3 4JJ", "47 Montagu Avenue, NE3 4JJ", "147 Montagu Avenue, NE3 4JJ"]
    a = Address(house_number="47", street="Montagu Avenue", postcode="NE3 4JJ")
    assert match_address(a, options, text=str) == options[1]
    by_uprn = Address(uprn="99", house_number="1", street="Nowhere")
    assert match_address(by_uprn, [("0099", "x"), ("1", "y")], text=lambda o: o[1], uprn=lambda o: o[0]) == ("0099", "x")


def test_parse_date_year_inference() -> None:
    assert parse_date("Thursday 1st October", today=date(2026, 9, 30)) == date(2026, 10, 1)
    assert parse_date("2 January", today=date(2026, 12, 30)) == date(2027, 1, 2)
    assert parse_date("29 December", today=date(2027, 1, 3)) == date(2026, 12, 29)
    assert parse_date("01/10/2026") == date(2026, 10, 1)
    assert parse_date("2026-10-01") == date(2026, 10, 1)


def test_tidy_dedupes_sorts_and_fills_icons() -> None:
    d1, d2 = date(2026, 10, 2), date(2026, 10, 1)
    out = tidy([Collection(d1, " Garden  waste "), Collection(d1, "Garden waste"), Collection(d2, "Non-recyclable")], {})
    assert out == [Collection(d2, "Non-recyclable", Icon.GENERAL_WASTE), Collection(d1, "Garden waste", Icon.GARDEN)]


@pytest.mark.parametrize(
    ("label", "colour"),
    [
        ("Recycling (Blue Bin)", "Blue"),
        ("Grey bin - general waste", "Grey"),
        ("Brown garden waste bin", "Brown"),
        ("Garden/Green Waste (Brown bin)", "Brown"),
        ("Green bin (garden waste)", "Green"),
        ("Mixed dry recycling (blue lidded bin) and glass (black box or basket)", "Blue"),
        ("Food and garden waste (brown-lidded bin)", "Brown"),
        ("Plastic and Cans (White Sack)", "White"),
        ("Empty Bin BLUE 240", "Blue"),
        ("Household Waste (Grey)", "Grey"),
        ("Brown (Food Waste)", "Brown"),
        ("Gray bin", "Grey"),
        ("Burgundy bin (general waste)", "Burgundy"),
        ("Brown garden waste wheeled bin", "Brown"),
        ("BLACK 240L", "Black"),
        ("Empty Bin 240L Black", "Black"),
        ("Empty 180L Blue", "Blue"),
        ("Blue 240L (paper and cardboard bin)", "Blue"),
        ("RECYCLING - BROWN", "Brown"),
        ("Black refuse", "Black"),
        ("Brown Composting", "Brown"),
        ("Grey food waste", "Grey"),
        ("Green non-recyclable", "Green"),
        ("Green Garden Waste", None),
        ("Pink Week", None),
        ("Green waste", None),
        ("Green garden waste", None),
        ("Garden waste", None),
        ("Royal Greenwich black top bin schedule", "Black"),
        ("Vale of White Horse collection", None),
        ("Non-recyclable waste", None),
    ],
)
def test_colour_of(label: str, colour: str | None) -> None:
    assert colour_of(label) == colour
