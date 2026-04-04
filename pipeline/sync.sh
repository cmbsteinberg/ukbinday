#!/usr/bin/env bash
set -euo pipefail

# Top-level sync: runs both upstream syncs, then regenerates the disabled list.
#
# Usage:
#   pipeline/sync.sh                    # sync both sources
#   pipeline/sync.sh --include-unmerged  # also check unmerged UKBCD PRs

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=== Syncing HACS scrapers ==="
bash "${SCRIPT_DIR}/hacs/sync.sh"

echo ""
echo "=== Syncing UKBCD scrapers ==="
bash "${SCRIPT_DIR}/ukbcd/sync.sh" "$@"

echo ""
echo "=== Regenerating disabled scrapers list ==="
if [ -f "tests/integration_output.json" ]; then
    uv run python -m scripts.generate_disabled_list
else
    echo "Skipping: no integration_output.json found. Run integration tests first."
fi

echo ""
echo "Done. Run 'uv run pytest tests/test_ci.py -v' to verify."
