#!/usr/bin/env bash
# Build locally and deploy a Vercel preview; the preview URL is the last line of stdout.
# Serves VERCEL.md phase 0 (spike) and phase 4 (council probe against a preview).
#
#   URL=$(scripts/vercel/preview.sh)
#   scripts/vercel/spike.sh "$URL"
#
# Needs a linked project (.vercel/project.json). If it is missing, run once:
#   npx vercel@latest link
# Progress goes to stderr, so $(...) captures only the URL.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/../.."
VERCEL=(npx --yes vercel@latest)

if [ ! -f .vercel/project.json ]; then
  echo "preview: project not linked; run: npx vercel@latest link" >&2
  exit 1
fi

# Env vars for the preview environment, then a local build into .vercel/output
"${VERCEL[@]}" pull --yes --environment=preview >&2
"${VERCEL[@]}" build >&2            # no --prod: a preview build
# stdout of `deploy` is always the deployment URL (Vercel CLI docs)
"${VERCEL[@]}" deploy --prebuilt | tail -n 1
