#!/usr/bin/env python3
"""
patch_compat.py — Patch hacs compat shim files for async httpx.

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


def _patch_imports(file_path: Path) -> None:
    """Rewrite waste_collection_schedule and requests imports in a compat file."""
    if not file_path.exists():
        return
    source = file_path.read_text()
    original = source
    # Rewrite waste_collection_schedule imports to local compat
    source = source.replace(
        "from waste_collection_schedule import Collection",
        "from api.compat.hacs import Collection",
    )
    source = source.replace(
        "from waste_collection_schedule.exceptions import",
        "from api.compat.hacs.exceptions import",
    )
    # Rewrite requests -> httpx (sync, since Cloud9Client uses Session)
    source = source.replace("import requests", "import httpx")
    source = source.replace("requests.Session()", "httpx.Client(follow_redirects=True)")
    if source != original:
        file_path.write_text(source)
        print(f"  Patched imports in {file_path}")


def patch(wcs_dir: Path) -> None:
    ssl_error = wcs_dir / "service" / "SSLError.py"
    if ssl_error.exists():
        ssl_error.write_text(SSLERROR_REPLACEMENT)
        print(f"  Patched {ssl_error}")
    else:
        print(f"  Warning: {ssl_error} not found, skipping")

    # Patch imports in other compat service files
    uk_cloud9 = wcs_dir / "service" / "uk_cloud9_apps.py"
    _patch_imports(uk_cloud9)


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
