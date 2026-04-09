#!/usr/bin/env bash
set -euo pipefail

# Config
REPO="mampfes/hacs_waste_collection_schedule"
BRANCH="master"
SOURCE_DIR="custom_components/waste_collection_schedule/waste_collection_schedule/source"
WCS_DIR="custom_components/waste_collection_schedule/waste_collection_schedule"
PATTERN="*_gov_uk.py"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PIPELINE_DIR="$(dirname "$SCRIPT_DIR")"
PROJECT_ROOT="$(dirname "$PIPELINE_DIR")"
API_DIR="${PROJECT_ROOT}/api"
LOCAL_DIR="${PIPELINE_DIR}/upstream/hacs"
SCRAPERS_DIR="${API_DIR}/scrapers"
COMPAT_DIR="${API_DIR}/compat/hacs"
PATCH_SCRIPT="${SCRIPT_DIR}/patch_scrapers.py"
PATCH_COMPAT_SCRIPT="${SCRIPT_DIR}/patch_compat.py"
VERSION_FILE="${SCRIPT_DIR}/.upstream_version"

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

# --- Sync compat/hacs support package ---
echo ""
echo "=== Syncing compat/hacs package ==="

COMPAT_FILES=(
    "collection.py"
    "exceptions.py"
)
COMPAT_SERVICE_FILES=(
    "ICS.py"
    "SSLError.py"
    "uk_cloud9_apps.py"
)

mkdir -p "${COMPAT_DIR}/service"

for f in "${COMPAT_FILES[@]}"; do
    echo "Copying ${f}..."
    cp "$CLONE_DIR/${WCS_DIR}/${f}" "${COMPAT_DIR}/${f}"
done

for f in "${COMPAT_SERVICE_FILES[@]}"; do
    echo "Copying service/${f}..."
    cp "$CLONE_DIR/${WCS_DIR}/service/${f}" "${COMPAT_DIR}/service/${f}"
done

# Patch compat files (SSLError.py: requests -> httpx)
echo "Patching compat/hacs files..."
python3 "$PATCH_COMPAT_SCRIPT" "$COMPAT_DIR"

# Write __init__.py (imports only what our scrapers need)
cat > "${COMPAT_DIR}/__init__.py" << 'PYEOF'
from .collection import Collection, CollectionBase, CollectionGroup  # noqa: F401
PYEOF

# Empty service __init__.py
touch "${COMPAT_DIR}/service/__init__.py"

echo "compat/hacs package synced."

# Remove overridden HACS scrapers (replaced by UKBCD equivalents)
echo "Removing overridden HACS scrapers..."
python3 -c "
import json, pathlib
overrides = json.loads(pathlib.Path('${PIPELINE_DIR}/overrides.json').read_text())
scrapers_dir = pathlib.Path('${SCRAPERS_DIR}')
for entry in overrides.get('hacs_to_ukbcd', {}).values():
    hacs_file = scrapers_dir / (entry['hacs_scraper'] + '.py')
    if hacs_file.exists():
        hacs_file.unlink()
        print(f'  Removed {hacs_file.name} (replaced by {entry[\"ukbcd_scraper\"]})')
"

# Lint and auto-fix scrapers
echo "Running ruff check --fix on scrapers..."
uv run ruff check --fix --ignore E402,E701,E722,E741,F403,F405,F821,F841,W293 "$SCRAPERS_DIR" || true

# Regenerate admin lookup (UKBCD sync needs this to know what HACS covers)
echo ""
echo "=== Regenerating admin lookup ==="
uv run python -m scripts.generate_admin_lookup

# Save the version
echo "$latest_sha" > "$VERSION_FILE"
echo "Version saved: ${latest_sha}"
