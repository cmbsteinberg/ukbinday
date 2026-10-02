#!/usr/bin/env bash
# Create the R2 bucket and a bucket-scoped S3 key, and write R2_* into an env file.
# Serves VERCEL.md phase 1 (ICS cache to R2). Safe to re-run: an existing bucket is kept,
# and a new key is minted each time (delete old ones under Manage Account -> Account API Tokens).
#
#   CLOUDFLARE_API_TOKEN=... scripts/vercel/cf_setup.sh /tmp/vercel.env
#
# Before running, in the dashboard:
#   1. R2 -> enable it (adds the payment method; R2 bills past the free tier).
#   2. Manage Account -> Account API Tokens -> Create Token, with
#        Account / Workers R2 Storage / Edit     (create the bucket)
#        Account / Account API Tokens / Edit     (mint the bucket-scoped key)
#        Zone    / DNS               / Edit, zone ukbinday.co.uk   (for cutover.sh)
#      That is CLOUDFLARE_API_TOKEN, used by this script and cutover.sh. The app never sees it.
#
# The S3 key comes from the Cloudflare docs (r2/api/tokens): an account token with
# "Workers R2 Storage Bucket Item Write" on the bucket resource; Access Key ID is the token
# id, Secret Access Key is the SHA-256 of the token value.
# Env: CLOUDFLARE_API_TOKEN (required), R2_BUCKET (default bins), CF_ACCOUNT_ID (default:
# the token's only account).
set -euo pipefail

[ $# -eq 1 ] || { echo "usage: $0 <env-file>" >&2; exit 2; }
FILE="$1"
: "${CLOUDFLARE_API_TOKEN:?set CLOUDFLARE_API_TOKEN}"
BUCKET="${R2_BUCKET:-bins}"
API=https://api.cloudflare.com/client/v4

cf() {  # cf METHOD PATH [JSON]; prints .result, exits on API errors
  local out
  out="$(curl -sS -X "$1" "$API$2" -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" \
    -H 'Content-Type: application/json' ${3:+--data "$3"})"
  if [ "$(jq -r .success <<<"$out")" != true ]; then
    echo "cf_setup: $1 $2 failed: $(jq -c .errors <<<"$out")" >&2; return 1
  fi
  jq .result <<<"$out"
}

set_var() {  # set_var KEY VALUE: replace or append in $FILE, never printing the value
  touch "$FILE"; chmod 600 "$FILE"
  grep -v "^$1=" "$FILE" > "$FILE.tmp" || true
  printf '%s=%s\n' "$1" "$2" >> "$FILE.tmp"
  mv "$FILE.tmp" "$FILE"
}

ACCOUNT="${CF_ACCOUNT_ID:-}"
if [ -z "$ACCOUNT" ]; then
  accounts="$(cf GET /accounts)"
  [ "$(jq length <<<"$accounts")" -eq 1 ] || { echo "cf_setup: token sees several accounts; set CF_ACCOUNT_ID" >&2; jq -r '.[] | "  \(.id)  \(.name)"' <<<"$accounts" >&2; exit 1; }
  ACCOUNT="$(jq -r '.[0].id' <<<"$accounts")"
fi
echo "cf_setup: account $ACCOUNT"

if cf GET "/accounts/$ACCOUNT/r2/buckets/$BUCKET" >/dev/null 2>&1; then
  echo "cf_setup: bucket $BUCKET exists"
else
  cf POST "/accounts/$ACCOUNT/r2/buckets" "$(jq -nc --arg n "$BUCKET" '{name: $n, locationHint: "weur"}')" >/dev/null
  echo "cf_setup: created bucket $BUCKET (weur)"
fi

GROUP="$(cf GET "/accounts/$ACCOUNT/tokens/permission_groups" | jq -r '.[] | select(.name == "Workers R2 Storage Bucket Item Write") | .id')"
[ -n "$GROUP" ] || { echo "cf_setup: permission group not found" >&2; exit 1; }
BODY="$(jq -nc --arg g "$GROUP" --arg r "com.cloudflare.edge.r2.bucket.${ACCOUNT}_default_${BUCKET}" \
  --arg n "bins-r2-$BUCKET-$(date +%Y%m%d)" \
  '{name: $n, policies: [{effect: "allow", resources: {($r): "*"}, permission_groups: [{id: $g}]}]}')"
token="$(cf POST "/accounts/$ACCOUNT/tokens" "$BODY")"

set_var R2_ACCOUNT_ID "$ACCOUNT"
set_var R2_BUCKET "$BUCKET"
set_var R2_ACCESS_KEY_ID "$(jq -r .id <<<"$token")"
set_var R2_SECRET_ACCESS_KEY "$(jq -r .value <<<"$token" | tr -d '\n' | shasum -a 256 | cut -d' ' -f1)"
echo "cf_setup: wrote R2_* to $FILE (token $(jq -r .name <<<"$token"))"
