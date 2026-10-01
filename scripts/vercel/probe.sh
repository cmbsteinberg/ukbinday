#!/usr/bin/env bash
# Run the council probe against a deployment: every sampled case through /lookup, diffed
# against the last live run. Serves VERCEL.md phase 4 (council probe).
#
#   scripts/vercel/probe.sh https://<preview>.vercel.app [extra scripts.vercel_probe args]
#
# Leave TURNSTILE_SECRET unset on the preview. Writes /tmp/vercel_probe.json.
# VERCEL_BYPASS (as for spike.sh) is passed on as the Deployment Protection bypass secret.
set -euo pipefail

[ $# -ge 1 ] || { echo "usage: $0 <base-url> [probe args]" >&2; exit 2; }
cd "$(dirname "${BASH_SOURCE[0]}")/../.."
VERCEL_AUTOMATION_BYPASS_SECRET="${VERCEL_BYPASS:-${VERCEL_AUTOMATION_BYPASS_SECRET:-}}" \
  exec uv run python -m scripts.vercel_probe --base-url "$1" --json /tmp/vercel_probe.json "${@:2}"
