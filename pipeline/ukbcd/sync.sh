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

CLONE_DIR=$(mktemp -d)
trap 'rm -rf "$CLONE_DIR"' EXIT

# Shallow clone
echo "Cloning ${REPO} (shallow)..."
git clone --depth 1 --branch "$BRANCH" "https://github.com/${REPO}.git" "$CLONE_DIR"

# Create local dir
mkdir -p "$LOCAL_DIR"

# Copy input.json to local dir for reference
cp "$CLONE_DIR/$INPUT_JSON" "$LOCAL_DIR/input.json"

# Run the patch script
# It will read input.json, find corresponding files in CLONE_DIR/SOURCE_DIR,
# filter them, and copy/patch them to SCRAPERS_DIR
echo "Running patch_scrapers.py..."
uv run python "$PATCH_SCRIPT" "$CLONE_DIR" "$SCRAPERS_DIR"

echo "Done."
