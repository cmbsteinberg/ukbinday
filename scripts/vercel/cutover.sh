#!/usr/bin/env bash
# Point ukbinday.co.uk and www at Vercel (Cloudflare DNS), or put them back.
# Serves VERCEL.md phase 5. Hetzner and Vercel share the R2 bucket, so either direction
# moves no data; the old records are saved first and --rollback restores them.
#
#   scripts/vercel/cutover.sh --dry-run          # print the record changes, change nothing
#   scripts/vercel/cutover.sh                    # add domains to Vercel, swap the records
#   scripts/vercel/cutover.sh --yes              # the same without the typed confirmation (no tty, e.g. `!`)
#   scripts/vercel/cutover.sh --rollback .vercel/dns_backup_<stamp>.json
#
# Steps: check the latest production deployment answers /api/v2/status; `vercel domains add`
# both names to the linked project; read Vercel's recommended A / CNAME for this project
# (GET /v6/domains/<d>/config, falling back to 76.76.21.21 / cname.vercel-dns.com); save
# the current A/AAAA/CNAME records of both names to .vercel/dns_backup_<stamp>.json; then,
# after you type "cutover", make each name exactly one record: apex A -> Vercel's IP,
# www CNAME -> Vercel's target, unproxied (Vercel issues the certificate), TTL 60. The
# apex AAAA (Hetzner's IPv6) is deleted, or IPv6 clients would stay on Hetzner. MX, TXT and
# everything else in the zone is left alone. Existing records are overwritten in place
# where possible, so a name is never without an answer for more than one API call.
# Env: CLOUDFLARE_API_TOKEN (Zone DNS Edit on the zone; see cf_setup.sh), DOMAIN (default
# ukbinday.co.uk), VERCEL_BYPASS (Deployment Protection bypass, for the health check). Needs a linked project, vercel login, jq.
set -euo pipefail

DOMAIN="${DOMAIN:-ukbinday.co.uk}"
NAMES=("$DOMAIN" "www.$DOMAIN")
MODE=run BACKUP="" YES=""
case "${1:-}" in
  '') ;;
  --yes) YES=1 ;;
  --dry-run) MODE=dry ;;
  --rollback) MODE=rollback; BACKUP="${2:?usage: $0 --rollback <backup.json>}"; [ -f "$BACKUP" ] || { echo "cutover: $BACKUP not found" >&2; exit 2; } ;;
  *) echo "usage: $0 [--dry-run | --yes | --rollback <backup.json> [--yes]]" >&2; exit 2 ;;
esac
[ "${3:-}" = --yes ] && YES=1
: "${CLOUDFLARE_API_TOKEN:?set CLOUDFLARE_API_TOKEN}"
cd "$(dirname "${BASH_SOURCE[0]}")/../.."
[ -f .vercel/project.json ] || { echo "cutover: project not linked; run: npx vercel@latest link" >&2; exit 1; }
VERCEL=(npx --yes vercel@latest)
PROJECT="$(jq -r .projectId .vercel/project.json)"
ORG="$(jq -r .orgId .vercel/project.json)"
API=https://api.cloudflare.com/client/v4

cf() {  # cf METHOD PATH [JSON]; prints .result, exits on API errors
  local out
  out="$(curl -sS -X "$1" "$API$2" -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" \
    -H 'Content-Type: application/json' ${3:+--data "$3"})"
  [ "$(jq -r .success <<<"$out")" = true ] || { echo "cutover: $1 $2 failed: $(jq -c .errors <<<"$out")" >&2; exit 1; }
  jq .result <<<"$out"
}

ZONE="$(cf GET "/zones?name=$DOMAIN" | jq -r '.[0].id // empty')"
[ -n "$ZONE" ] || { echo "cutover: zone $DOMAIN not visible to the token" >&2; exit 1; }

current() {  # current NAME: its A/AAAA/CNAME records as a JSON array
  cf GET "/zones/$ZONE/dns_records?name=$1&per_page=100" \
    | jq '[.[] | select(.type == "A" or .type == "AAAA" or .type == "CNAME") | {id, type, name, content, ttl, proxied}]'
}

apply() {  # apply NAME DESIRED_JSON_ARRAY: make NAME's A/AAAA/CNAME records exactly DESIRED
  local name="$1" want="$2" have n_have n_want i rec
  have="$(current "$name")"; n_have="$(jq length <<<"$have")"; n_want="$(jq length <<<"$want")"
  # Surplus records go first: a CNAME can't be written while other records share the name
  for ((i = n_want; i < n_have; i++)); do
    cf DELETE "/zones/$ZONE/dns_records/$(jq -r ".[$i].id" <<<"$have")" >/dev/null
    echo "  $name: - $(jq -r ".[$i] | \"\(.type) \(.content)\"" <<<"$have")"
  done
  for ((i = 0; i < n_want; i++)); do
    rec="$(jq -c --arg n "$name" ".[$i] | {type, name: \$n, content, ttl, proxied}" <<<"$want")"
    if [ "$i" -lt "$n_have" ]; then
      cf PUT "/zones/$ZONE/dns_records/$(jq -r ".[$i].id" <<<"$have")" "$rec" >/dev/null
      echo "  $name: $(jq -r ".[$i] | \"\(.type) \(.content)\"" <<<"$have") -> $(jq -r '"\(.type) \(.content)"' <<<"$rec")"
    else
      cf POST "/zones/$ZONE/dns_records" "$rec" >/dev/null
      echo "  $name: + $(jq -r '"\(.type) \(.content)"' <<<"$rec")"
    fi
  done
}

confirm() {
  [ -n "$YES" ] && return 0
  local reply; read -r -p "Type $1 to go ahead: " reply </dev/tty
  [ "$reply" = "$1" ] || { echo "cutover: not confirmed, nothing changed" >&2; exit 1; }
}

if [ "$MODE" = rollback ]; then
  echo "cutover: restoring from $BACKUP"
  for name in "${NAMES[@]}"; do
    echo "  $name now: $(current "$name" | jq -c '[.[] | "\(.type) \(.content)"]')  restore: $(jq -c --arg n "$name" '[.[$n][] | "\(.type) \(.content)"]' "$BACKUP")"
  done
  confirm rollback
  for name in "${NAMES[@]}"; do apply "$name" "$(jq -c --arg n "$name" '.[$n]' "$BACKUP")"; done
  echo "cutover: rolled back. Remove the domains from Vercel later if you're staying on Hetzner."
  exit 0
fi

# Production must answer before any DNS moves
PROD="$("${VERCEL[@]}" api "/v6/deployments?projectId=$PROJECT&target=production&state=READY&limit=1" --raw | jq -r '.deployments[0].url // empty')"
[ -n "$PROD" ] || { echo "cutover: no ready production deployment; run the deploy-vercel job first" >&2; exit 1; }
# Standard Deployment Protection covers *.vercel.app URLs (not the custom domain), so
# send the automation bypass secret when there is one, as spike.sh and probe.sh do
code="$(curl -s -o /dev/null -w '%{http_code}' ${VERCEL_BYPASS:+-H "x-vercel-protection-bypass: $VERCEL_BYPASS"} "https://$PROD/api/v2/status")"
echo "cutover: production $PROD /api/v2/status -> $code"
[ "$code" = 200 ] || { echo "cutover: production isn't healthy (Deployment Protection on production would also do this)" >&2; exit 1; }

if [ "$MODE" = run ]; then
  for name in "${NAMES[@]}"; do
    # The API rather than `vercel domains add`, which answered "User not found" for a team project
    "${VERCEL[@]}" api "/v10/projects/$PROJECT/domains?teamId=$ORG" -X POST -F "name=$name" --raw >/dev/null 2>&1 \
      || echo "cutover: adding $name to the project failed (fine if it's already there)" >&2
  done
fi

config="$("${VERCEL[@]}" api "/v6/domains/$DOMAIN/config?projectIdOrName=$PROJECT" --raw 2>/dev/null || echo '{}')"
IP="$(jq -r '.recommendedIPv4[0].value[0] // "76.76.21.21"' <<<"$config")"
CNAME="$(jq -r '.recommendedCNAME[0].value // "cname.vercel-dns.com"' <<<"$config" | sed 's/\.$//')"
echo "cutover: Vercel wants $DOMAIN A $IP, www.$DOMAIN CNAME $CNAME"

STAMP="$(date +%Y%m%d-%H%M%S)"
SAVE=".vercel/dns_backup_$STAMP.json"
# Plain assignments, so a failed API call stops the script (set -e) before anything is saved
REC_APEX="$(current "$DOMAIN")"
REC_WWW="$(current "www.$DOMAIN")"
jq -n --arg a "$DOMAIN" --arg w "www.$DOMAIN" --argjson ra "$REC_APEX" --argjson rw "$REC_WWW" \
  '{($a): $ra, ($w): $rw}' > "$SAVE"
echo "cutover: current records saved to $SAVE"
jq -r 'to_entries[] | .key as $n | .value[] | "  \($n): \(.type) \(.content) (proxied \(.proxied))"' "$SAVE"

WANT_APEX="$(jq -nc --arg c "$IP" '[{type: "A", content: $c, ttl: 60, proxied: false}]')"
WANT_WWW="$(jq -nc --arg c "$CNAME" '[{type: "CNAME", content: $c, ttl: 60, proxied: false}]')"
if [ "$MODE" = dry ]; then
  echo "cutover: dry run; would set $DOMAIN -> A $IP and www.$DOMAIN -> CNAME $CNAME, deleting other A/AAAA/CNAME on both"
  exit 0
fi

confirm cutover
apply "$DOMAIN" "$WANT_APEX"
apply "www.$DOMAIN" "$WANT_WWW"
echo "cutover: done. Rollback: $0 --rollback $SAVE"
echo "cutover: next: npx vercel@latest domains verify $DOMAIN; then watch logs.sh and the refresh heartbeat"
