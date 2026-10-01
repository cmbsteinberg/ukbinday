#!/usr/bin/env bash
# Trigger the refresh cron route by hand and show what it did.
# Serves VERCEL.md phase 2 (refresh endpoint) and the post-cutover watch.
#
#   CRON_SECRET=... scripts/vercel/refresh_now.sh https://ukbinday.co.uk        # shard 0 of 1
#   CRON_SECRET=... scripts/vercel/refresh_now.sh https://<preview>.vercel.app 1 4
#
# Env: CRON_SECRET (required; the same value as on the project), VERCEL_BYPASS (optional,
# for a protected preview; sent as x-vercel-protection-bypass).
# The route can run up to ~250 s, so the request is allowed 310 s.
set -euo pipefail

[ $# -ge 1 ] && [ $# -le 3 ] || { echo "usage: $0 <base-url> [shard] [of]" >&2; exit 2; }
: "${CRON_SECRET:?set CRON_SECRET}"
BASE="${1%/}"; SHARD="${2:-0}"; OF="${3:-1}"
API="$BASE/api/v1"

HDR=()
[ -z "${VERCEL_BYPASS:-}" ] || HDR=(-H "x-vercel-protection-bypass: $VERCEL_BYPASS")

echo "refresh_now: shard $SHARD of $OF on $BASE (can take minutes)" >&2
# the secret goes through a config on stdin, so it never appears in the process list
body="$(mktemp)"; trap 'rm -f "$body"' EXIT
code="$(printf 'header = "Authorization: Bearer %s"\n' "$CRON_SECRET" |
  curl -sS --max-time 310 -K - ${HDR[@]+"${HDR[@]}"} -o "$body" -w '%{http_code}' \
    --get --data-urlencode "shard=$SHARD" --data-urlencode "of=$OF" "$API/internal/refresh")"
echo "refresh_now: HTTP $code" >&2
jq . "$body" 2>/dev/null || cat "$body"
[ "$code" = 200 ] || exit 1

echo >&2; echo "refresh_now: heartbeat from /metrics" >&2
curl -sS --max-time 30 ${HDR[@]+"${HDR[@]}"} "$API/metrics" | jq '.ics_cache'
