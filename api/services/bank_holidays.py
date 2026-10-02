"""Bank holiday names from the committed gov.uk snapshot (api/data/bank_holidays.json).

Refresh with `uv run python -m scripts.lookup.fetch_bank_holidays`. No network at runtime.
"""

from __future__ import annotations

import json
from datetime import date
from functools import cache
from pathlib import Path

_DATA = Path(__file__).resolve().parent.parent / "data" / "bank_holidays.json"
_REGIONS = {"E": "england-and-wales", "W": "england-and-wales", "S": "scotland", "N": "northern-ireland"}


@cache
def _load() -> dict[str, dict[str, str]]:
    raw = json.loads(_DATA.read_text(encoding="utf-8"))
    return {region: {e["date"]: e["title"] for e in body["events"]} for region, body in raw.items()}


def holiday_name(lad: str, day: date) -> str | None:
    """The bank holiday on `day` where the LAD is, or None."""
    region = _REGIONS.get(lad[:1].upper())
    if region is None:
        return None
    return _load().get(region, {}).get(day.isoformat())
