#!/usr/bin/env bash
# Regenerate everything derived from the last live run
# (tests/output/lad_integration_output.json). Tests never call this; run it
# yourself after `uv run pytest tests/test_lad_integration.py`:
#   ./pipeline/ci/post_integration.sh
#
# The working rule lives in scripts/lad_status.py.

set -euo pipefail

cd "$(dirname "$0")/../.."

if [ ! -f tests/output/lad_integration_output.json ]; then
    echo "tests/output/lad_integration_output.json not found; run tests/test_lad_integration.py first" >&2
    exit 1
fi

# Annotate first: the coverage map and sankey read the `working` flag it writes.
echo "Annotating lad_lookup.json with test results..."
uv run python -m scripts.annotate_lad_working

echo "Regenerating coverage map..."
uv run python -m scripts.coverage.generate_coverage_map

echo "Regenerating sankey diagram and badge..."
uv run python -m scripts.generate_sankey

echo "Post-integration scripts complete."
