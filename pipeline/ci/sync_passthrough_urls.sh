#!/usr/bin/env bash
# Keeps the PASSTHROUGH_ICS entry in api/static/app.js in sync with the URL
# constant in api/scrapers/ukbcd_google_public_calendar_council.py.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SCRAPER="$ROOT/api/scrapers/ukbcd_google_public_calendar_council.py"
APP_JS="$ROOT/api/static/app.js"
KEY="ukbcd_google_public_calendar_council"

URL=$(awk -F'"' '/^URL = "/{print $2; exit}' "$SCRAPER")
if [ -z "${URL:-}" ]; then
  echo "sync_passthrough_urls: could not read URL from $SCRAPER" >&2
  exit 1
fi

tmp=$(mktemp)
awk -v key="$KEY:" -v url="$URL" '
  pending && /"[^"]*"/ {
    sub(/"[^"]*"/, "\"" url "\"")
    pending = 0
    print
    next
  }
  index($0, key) {
    if ($0 ~ /"[^"]*"/) {
      sub(/"[^"]*"/, "\"" url "\"")
    } else {
      pending = 1
    }
  }
  { print }
' "$APP_JS" > "$tmp"

if ! cmp -s "$tmp" "$APP_JS"; then
  mv "$tmp" "$APP_JS"
  echo "sync_passthrough_urls: updated $APP_JS"
else
  rm "$tmp"
fi
