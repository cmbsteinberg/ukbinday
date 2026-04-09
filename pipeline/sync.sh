#!/usr/bin/env bash
set -euo pipefail

# Top-level sync: orchestrates HACS + UKBCD sync with input.json filtering.
#
# Uses pipeline/sync_all.py to:
#   1. Fetch input.json (source of truth for needed councils)
#   2. Sync HACS scrapers and filter out stale ones
#   3. Sync UKBCD scrapers to fill coverage gaps
#   4. Regenerate lookup files
#
# Usage:
#   pipeline/sync.sh                    # sync both sources
#   pipeline/sync.sh --include-unmerged  # also check unmerged UKBCD PRs

uv run python -m pipeline.sync_all "$@"
