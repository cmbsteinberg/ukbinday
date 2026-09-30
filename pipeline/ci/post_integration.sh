#!/usr/bin/env bash
# Post-integration-test regeneration scripts.
# Called automatically after integration tests, or run manually:
#   ./pipeline/ci/post_integration.sh

set -euo pipefail

cd "$(dirname "$0")/../.."

# Annotate first: the coverage map and sankey read the `working` flag it writes.
echo "Annotating lad_lookup.json with test results..."
uv run python -m scripts.annotate_lad_working

echo "Regenerating coverage map..."
uv run python -m scripts.coverage.generate_coverage_map

echo "Regenerating sankey diagram..."
uv run python -m scripts.generate_sankey

echo "Post-integration scripts complete."
