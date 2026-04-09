#!/usr/bin/env bash
set -euo pipefail

# Config
REPO="robbrad/UKBinCollectionData"
BRANCH="master"
SOURCE_DIR="uk_bin_collection/uk_bin_collection/councils"
INPUT_JSON="uk_bin_collection/tests/input.json"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PIPELINE_DIR="$(dirname "$SCRIPT_DIR")"
PROJECT_ROOT="$(dirname "$PIPELINE_DIR")"
API_DIR="${PROJECT_ROOT}/api"
LOCAL_DIR="${PIPELINE_DIR}/upstream/ukbcd"
SCRAPERS_DIR="${API_DIR}/scrapers"
PATCH_SCRIPT="${SCRIPT_DIR}/patch_scrapers.py"
CHECK_SCRIPT="${SCRIPT_DIR}/check_upstream_fixes.py"

# Parse flags
INCLUDE_UNMERGED=false
for arg in "$@"; do
  case "$arg" in
    --include-unmerged) INCLUDE_UNMERGED=true ;;
  esac
done

CLONE_DIR=$(mktemp -d)
trap 'rm -rf "$CLONE_DIR"' EXIT

# Shallow clone
echo "Cloning ${REPO} (shallow)..."
git clone --depth 1 --branch "$BRANCH" "https://github.com/${REPO}.git" "$CLONE_DIR"

# Check upstream branches/PRs for fixes to failing scrapers (disabled)
# if command -v gh &>/dev/null; then
#   echo "Checking upstream for unmerged fixes..."
#   if [ "$INCLUDE_UNMERGED" = true ]; then
#     uv run python "$CHECK_SCRIPT" --clone-dir "$CLONE_DIR" --include-unmerged || true
#   else
#     uv run python "$CHECK_SCRIPT" || true
#   fi
# else
#   echo "Skipping upstream check (gh CLI not available)"
# fi

# Create local dir
mkdir -p "$LOCAL_DIR"

# Copy input.json to local dir for reference
cp "$CLONE_DIR/$INPUT_JSON" "$LOCAL_DIR/input.json"

# Remove stale robbrad scrapers before re-patching
echo "Removing old robbrad scrapers..."
rm -f "$SCRAPERS_DIR"/ukbcd_*.py

# Run the patch script
# It will read input.json, find corresponding files in CLONE_DIR/SOURCE_DIR,
# filter them, find corresponding files, and copy/patch them to SCRAPERS_DIR
echo "Running patch_scrapers.py..."
uv run python "$PATCH_SCRIPT" "$CLONE_DIR" "$SCRAPERS_DIR"

# Regenerate test cases for ukbcd scrapers
echo "Generating ukbcd test cases lookup..."
uv run python -m pipeline.ukbcd.generate_test_lookup

echo "Done."
