#!/usr/bin/env bash
set -euo pipefail

# Config
REPO="mampfes/hacs_waste_collection_schedule"
BRANCH="master"
SOURCE_DIR="custom_components/waste_collection_schedule/waste_collection_schedule/source"
WCS_DIR="custom_components/waste_collection_schedule/waste_collection_schedule"
PATTERN="*_gov_uk.py"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PARENT_DIR="$(dirname "$SCRIPT_DIR")"
API_DIR="$(dirname "$PARENT_DIR")/api"
LOCAL_DIR="${SCRIPT_DIR}/waste_sources"
SCRAPERS_DIR="${API_DIR}/scrapers"
WCS_LOCAL_DIR="${API_DIR}/waste_collection_schedule"
PATCH_SCRIPT="${SCRIPT_DIR}/patch_scrapers.py"
PATCH_WCS_SCRIPT="${SCRIPT_DIR}/patch_wcs.py"
VERSION_FILE="${SCRIPT_DIR}/.gov_uk_sources_version"

API_BASE="https://api.github.com/repos/${REPO}"

# Check latest commit SHA
latest_sha=$(curl -sf "${API_BASE}/commits/${BRANCH}" | python3 -c "import sys,json; print(json.load(sys.stdin)['sha'])")

if [ -z "$latest_sha" ]; then
    echo "Error: Could not fetch latest commit SHA" >&2
    exit 1
fi

echo "Latest commit on ${BRANCH}: ${latest_sha}"

if [ -f "$VERSION_FILE" ]; then
    stored_sha=$(cat "$VERSION_FILE")
    if [ "$stored_sha" = "$latest_sha" ]; then
        echo "Already up to date."
        exit 0
    fi
    echo "New commits detected (stored: ${stored_sha:0:8}, latest: ${latest_sha:0:8})"
else
    echo "No version file found. Performing initial sync."
fi

CLONE_DIR=$(mktemp -d)
trap 'rm -rf "$CLONE_DIR"' EXIT

# Shallow clone
echo "Cloning ${REPO} (shallow)..."
git clone --depth 1 --branch "$BRANCH" "https://github.com/${REPO}.git" "$CLONE_DIR"

# Copy gov_uk source files
echo "Copying gov_uk source files..."
mkdir -p "$LOCAL_DIR"
cp "$CLONE_DIR/${SOURCE_DIR}"/${PATTERN} "$LOCAL_DIR/"
count=$(ls -1 "$LOCAL_DIR"/${PATTERN} | wc -l | tr -d ' ')
echo "Copied ${count} files to ${LOCAL_DIR}/"

# Patch scrapers for async httpx
echo "Patching scrapers for async httpx..."
python3 "$PATCH_SCRIPT" "$LOCAL_DIR" "$SCRAPERS_DIR"

# --- Sync waste_collection_schedule support package ---
echo ""
echo "=== Syncing waste_collection_schedule package ==="

WCS_FILES=(
    "collection.py"
    "exceptions.py"
)
WCS_SERVICE_FILES=(
    "ICS.py"
    "SSLError.py"
)

mkdir -p "${WCS_LOCAL_DIR}/service"

for f in "${WCS_FILES[@]}"; do
    echo "Copying ${f}..."
    cp "$CLONE_DIR/${WCS_DIR}/${f}" "${WCS_LOCAL_DIR}/${f}"
done

for f in "${WCS_SERVICE_FILES[@]}"; do
    echo "Copying service/${f}..."
    cp "$CLONE_DIR/${WCS_DIR}/service/${f}" "${WCS_LOCAL_DIR}/service/${f}"
done

# Patch WCS files (SSLError.py: requests -> httpx)
echo "Patching waste_collection_schedule files..."
python3 "$PATCH_WCS_SCRIPT" "$WCS_LOCAL_DIR"

# Write __init__.py (imports only what our scrapers need)
cat > "${WCS_LOCAL_DIR}/__init__.py" << 'PYEOF'
from .collection import Collection, CollectionBase, CollectionGroup  # noqa: F401
PYEOF

# Empty service __init__.py
touch "${WCS_LOCAL_DIR}/service/__init__.py"

echo "waste_collection_schedule package synced."

# Lint and auto-fix scrapers
echo "Running ruff check --fix on scrapers..."
uv run ruff check --fix --ignore E722 "$SCRAPERS_DIR"

# Regenerate lookup files
echo ""
echo "=== Regenerating lookup files ==="

echo "Generating admin scraper lookup..."
uv run python -m src.scripts.address_lookup.generate_admin_lookup

echo "Generating test cases lookup..."
uv run python -m src.scripts.address_lookup.generate_test_lookup

# Save the version
echo "$latest_sha" > "$VERSION_FILE"
echo "Version saved: ${latest_sha}"
