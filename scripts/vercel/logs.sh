#!/usr/bin/env bash
# Deployment summary and recent runtime logs, to confirm the region, functions and errors.
# Serves VERCEL.md phase 0 (spike) and the post-cutover watch. Hobby keeps logs for 1 hour.
#
#   scripts/vercel/logs.sh https://<preview>.vercel.app [since, default 30m]
#
# Needs a linked project and `vercel login` (or VERCEL_TOKEN).
set -euo pipefail

[ $# -ge 1 ] || { echo "usage: $0 <deployment-url> [since]" >&2; exit 2; }
cd "$(dirname "${BASH_SOURCE[0]}")/../.."
VERCEL=(npx --yes vercel@latest)

echo "== inspect" >&2
"${VERCEL[@]}" inspect "$1"
echo "== runtime logs (errors, last ${2:-30m})" >&2
"${VERCEL[@]}" logs "$1" --level error --since "${2:-30m}" --limit 50
