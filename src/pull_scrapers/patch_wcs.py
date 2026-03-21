#!/usr/bin/env python3
"""
patch_wcs.py — Patch waste_collection_schedule support files for async httpx.

Currently patches:
  - service/SSLError.py: Convert requests-based legacy SSL session to httpx.
"""

from __future__ import annotations

import sys
from pathlib import Path

# SSLError.py replacement — the upstream version uses requests + urllib3.
# We replace the entire file with an httpx equivalent.
SSLERROR_REPLACEMENT = """\
import ssl

import httpx


def get_legacy_session():
    ctx = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
    ctx.options |= 0x4  # OP_LEGACY_SERVER_CONNECT
    return httpx.AsyncClient(verify=ctx, follow_redirects=True)
"""


def patch(wcs_dir: Path) -> None:
    ssl_error = wcs_dir / "service" / "SSLError.py"
    if ssl_error.exists():
        ssl_error.write_text(SSLERROR_REPLACEMENT)
        print(f"  Patched {ssl_error}")
    else:
        print(f"  Warning: {ssl_error} not found, skipping")


def main() -> int:
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <wcs_dir>", file=sys.stderr)
        return 1

    wcs_dir = Path(sys.argv[1])
    if not wcs_dir.is_dir():
        print(f"Error: {wcs_dir} is not a directory", file=sys.stderr)
        return 1

    patch(wcs_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
