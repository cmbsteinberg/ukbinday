"""Bank holiday lookup from the committed gov.uk snapshot."""

from __future__ import annotations

from datetime import date

import pytest

from api.services.bank_holidays import holiday_name

pytestmark = pytest.mark.ci


def test_christmas_day_england() -> None:
    assert holiday_name("E06000001", date(2026, 12, 25)) == "Christmas Day"


def test_scotland_only_holiday() -> None:
    assert holiday_name("S12000033", date(2026, 11, 30)) is not None  # St Andrew's Day
    assert holiday_name("E06000001", date(2026, 11, 30)) is None
    assert holiday_name("S12000033", date(2027, 1, 4)) is not None  # 2 January, moved
    assert holiday_name("E06000001", date(2027, 1, 4)) is None


def test_ordinary_day() -> None:
    assert holiday_name("E06000001", date(2026, 10, 7)) is None
