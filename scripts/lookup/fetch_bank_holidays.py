"""Refresh api/data/bank_holidays.json from gov.uk (the verbatim response body).

    uv run python -m scripts.lookup.fetch_bank_holidays
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx

URL = "https://www.gov.uk/bank-holidays.json"
OUT = Path(__file__).resolve().parents[2] / "api" / "data" / "bank_holidays.json"


def main() -> None:
    body = httpx.get(URL, timeout=30, follow_redirects=True).raise_for_status().content
    json.loads(body)  # refuse to commit something that isn't JSON
    OUT.write_bytes(body)
    print(f"wrote {OUT} ({len(body)} bytes)")


if __name__ == "__main__":
    main()
