#!/usr/bin/env bash
# Push an env file to the linked Vercel project (one `vercel env add` per key).
# Serves VERCEL.md phase 4 (env vars).
#
#   cp scripts/vercel/env.example /tmp/vercel.env   # fill it in; keep it out of the repo
#   scripts/vercel/env_push.sh /tmp/vercel.env              # production (default)
#   scripts/vercel/env_push.sh /tmp/vercel.env preview
#
# Lines are KEY=VALUE (comments and blanks skipped, one pair of surrounding quotes
# stripped). Keys outside the expected list abort the run before anything is pushed.
# CRON_SECRET is generated (openssl rand -hex 32) when the file has none. Vercel stores it
# as sensitive and cannot show it again, so put your own in the file if you want to run
# scripts/vercel/refresh_now.sh. Values go to vercel on stdin, never argv, and are never printed.
# Needs a linked project (npx vercel@latest link). `env add --force` overwrites an existing
# variable of the same target, so there is no separate remove step.
set -euo pipefail

[ $# -ge 1 ] && [ $# -le 2 ] || { echo "usage: $0 <env-file> [production|preview]" >&2; exit 2; }
FILE="$1"
TARGET="${2:-production}"
case "$TARGET" in production|preview) ;; *) echo "env_push: target must be production or preview" >&2; exit 2 ;; esac
[ -f "$FILE" ] || { echo "env_push: $FILE not found" >&2; exit 2; }

cd "$(dirname "${BASH_SOURCE[0]}")/../.."
[ -f .vercel/project.json ] || { echo "env_push: project not linked; run: npx vercel@latest link" >&2; exit 1; }
VERCEL=(npx --yes vercel@latest)

EXPECTED=" ADDRESS_API_URL ADDRESS_API_COMPANY_ID TURNSTILE_SITE_KEY TURNSTILE_SECRET BASE_URL CORS_ORIGINS
 R2_ACCOUNT_ID R2_ACCESS_KEY_ID R2_SECRET_ACCESS_KEY R2_BUCKET CRON_SECRET ENV LOG_FORMAT SCRAPER_TIMEOUT
 ICS_REFRESH_CONCURRENCY RUN_REFRESH_JOB "
EXPECTED="$(printf '%s' "$EXPECTED" | tr '\n' ' ')"

KEYS=(); VALUES=(); BAD=()
while IFS= read -r line || [ -n "$line" ]; do
  line="${line%$'\r'}"
  case "$line" in ''|'#'*|[[:space:]]*'#'*) continue ;; esac
  line="${line#export }"
  case "$line" in *=*) ;; *) echo "env_push: skipping line without '=': ${line%%[!A-Za-z0-9_]*}" >&2; continue ;; esac
  key="${line%%=*}"; value="${line#*=}"
  case "$value" in \"*\") value="${value#\"}"; value="${value%\"}" ;; \'*\') value="${value#\'}"; value="${value%\'}" ;; esac
  case "$EXPECTED" in *" $key "*) ;; *) BAD+=("$key"); continue ;; esac
  [ -n "$value" ] || { echo "env_push: $key is empty, skipping" >&2; continue; }
  KEYS+=("$key"); VALUES+=("$value")
done <"$FILE"

if [ "${#BAD[@]}" -gt 0 ]; then
  echo "env_push: keys not in the expected list (REDIS_URL is deliberately absent); nothing pushed:" >&2
  printf '  %s\n' "${BAD[@]}" >&2
  exit 1
fi

GENERATED=""
case " ${KEYS[*]-} " in
  *" CRON_SECRET "*) ;;
  *) KEYS+=(CRON_SECRET); VALUES+=("$(openssl rand -hex 32)"); GENERATED=1
     echo "env_push: CRON_SECRET was not in the file; generated one (not shown)" >&2 ;;
esac

for i in "${!KEYS[@]}"; do
  key="${KEYS[$i]}"
  # value on stdin so it never shows in the process list or shell history
  printf %s "${VALUES[$i]}" | "${VERCEL[@]}" env add "$key" "$TARGET" --force --yes >/dev/null
  echo "env_push: $key -> $TARGET"
done

echo "env_push: ${#KEYS[@]} variables set on $TARGET. Redeploy for them to take effect."
if [ -n "$GENERATED" ]; then
  echo "env_push: the generated CRON_SECRET cannot be read back; for refresh_now.sh put your own in the file"
fi
