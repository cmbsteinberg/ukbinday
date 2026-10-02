#!/usr/bin/env bash
# Deploy a Vercel preview (built remotely by Vercel); the preview URL is the last line of stdout.
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

# Vercel builds from the upload, which honours .vercelignore and leaves out .env* files.
# A local `vercel build` + `deploy --prebuilt` doesn't: the Python builder put .env.local
# (and other ignored root files) in the function's file map, and the deploy then failed.
# stdout of `deploy` carries the URL (now inside trailing JSON); pick it out
"${VERCEL[@]}" deploy | grep -Eo 'https://[^" ]+\.vercel\.app' | tail -n 1
