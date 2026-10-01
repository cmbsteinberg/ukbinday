#!/usr/bin/env bash
# Phase 0 checks against a deployment: PASS/FAIL per item, exit 1 if any FAIL.
# Serves VERCEL.md phase 0 (spike) and doubles as a post-deploy smoke test.
#
#   scripts/vercel/spike.sh https://<preview>.vercel.app
#   scripts/vercel/spike.sh http://127.0.0.1:8766        # local run; the region check fails there
#
#   VERCEL_BYPASS=<secret>   Deployment Protection bypass for automation; sent as the
#                            x-vercel-protection-bypass header (project Settings ->
#                            Deployment Protection -> Protection Bypass for Automation)
#   CURL_MODULE / PDF_MODULE / HTTPX_MODULE
#                            council modules to try (default ashford = curl_cffi,
#                            trafford = pdfplumber, hartlepool = plain httpx)
#   REGION                   expected function region (default lhr1)
#
# Cases come from tests/lad_test_cases.json at run time (a sampled case first, then
# fixtures; the first that returns collections wins). The lookups hit live council sites.
set -uo pipefail

[ $# -eq 1 ] || { echo "usage: $0 <base-url>" >&2; exit 2; }
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BASE="${1%/}"
API="$BASE/api/v1"
CASES="$ROOT/tests/lad_test_cases.json"
REGION="${REGION:-lhr1}"
CURL_MODULE="${CURL_MODULE:-ashford}"
PDF_MODULE="${PDF_MODULE:-trafford}"
HTTPX_MODULE="${HTTPX_MODULE:-hartlepool}"
POSTCODE="${POSTCODE:-TS26 0BL}"   # Hartlepool

for tool in curl jq; do command -v "$tool" >/dev/null || { echo "spike: $tool not installed" >&2; exit 2; }; done

HDR=()
[ -z "${VERCEL_BYPASS:-}" ] || HDR=(-H "x-vercel-protection-bypass: $VERCEL_BYPASS")
# bash 3.2 (macOS) trips over an empty array under set -u, hence the ${HDR[@]+...} form
get() { curl -sS --max-time "${MAX_TIME:-70}" ${HDR[@]+"${HDR[@]}"} "$@"; }

FAILS=0
pass() { printf 'PASS  %s\n' "$*"; }
fail() { printf 'FAIL  %s\n' "$*"; FAILS=$((FAILS + 1)); }
check() { local label="$1"; shift; if "$@"; then pass "$label"; else fail "$label"; fi; }

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

echo "spike: $BASE (expect function region $REGION)"

# --- cold start: first /status vs the second ---------------------------------------
# curl -w gives total seconds; the first hit after a deploy pays import + lifespan.
t1="$(get -o "$TMP/s1" -D "$TMP/h1" -w '%{http_code} %{time_total}' "$API/status" 2>"$TMP/err")" || t1="000 0"
t2="$(get -o "$TMP/s2" -w '%{http_code} %{time_total}' "$API/status" 2>>"$TMP/err")" || t2="000 0"
if [ "${t1%% *}" = 200 ] && [ "${t2%% *}" = 200 ]; then
  pass "status 200; first ${t1##* }s, second ${t2##* }s (a cold start is the difference; it needs a fresh/idle deployment to show)"
  if [ "$(jq -r .status "$TMP/s1")" = healthy ]; then pass "status body: healthy, $(jq -r .scraper_count "$TMP/s1") scrapers"
  else fail "status body is not healthy: $(jq -c . "$TMP/s1")"; fi
else
  fail "/status returned ${t1%% *} then ${t2%% *}: $(head -c 200 "$TMP/err") $(head -c 200 "$TMP/s1" 2>/dev/null)"
  echo "spike: nothing else can work; if this is a 401 on a preview, set VERCEL_BYPASS" >&2
  exit 1
fi

# --- region: x-vercel-id is <edge>::<function region>::<id> for a function response --
vid="$(tr -d '\r' <"$TMP/h1" | awk -F': ' 'tolower($1) == "x-vercel-id" {print $2}')"
if [ -z "$vid" ]; then
  fail "region: no x-vercel-id header, so this is not a Vercel deployment (a local server answers like this)"
else
  fn_region="$(printf '%s' "$vid" | awk -F'::' 'NF >= 3 {print $2}')"
  if [ "$fn_region" = "$REGION" ]; then pass "region: function ran in $fn_region (x-vercel-id $vid)"
  else fail "region: function region '${fn_region:-none}' is not $REGION (x-vercel-id $vid)"; fi
fi

# --- councils ----------------------------------------------------------------------
n="$(get "$API/councils" | jq 'length' 2>/dev/null || echo 0)"
check "/councils lists $n councils (want > 0)" test "${n:-0}" -gt 0

# --- postcode -> LAD code -----------------------------------------------------------
lad="$(get "$API/council/${POSTCODE// /%20}" | jq -r '.council_id // empty' 2>/dev/null)"
case "$lad" in
  [EWSN][0-9]*) pass "/council/$POSTCODE -> $lad" ;;
  *) fail "/council/$POSTCODE returned no LAD code (got '${lad:-nothing}')" ;;
esac

# --- /lookup per module ---------------------------------------------------------------
# Try the module's cases in order until one returns >= 1 collection; echo the case's
# LAD, uprn and query string pairs to $TMP/case for the calendar check.
lookup_module() {  # <label> <module>
  local label="$1" module="$2" lad id resp n=0 tried=0
  lad="$(jq -r --arg m "$module" 'to_entries[] | select(.value.scraper_id == $m) | .key' "$CASES" | head -n 1)"
  if [ -z "$lad" ]; then fail "lookup ($label): module '$module' not in $CASES"; return; fi
  # sampled cases first, then fixtures
  while IFS=$'\t' read -r id; do
    tried=$((tried + 1))
    local args=(--data-urlencode "council=$lad") uprn
    uprn="$(jq -r --arg l "$lad" --arg id "$id" '.[$l].cases[] | select(.id == $id) | .params.uprn // "0"' "$CASES")"
    while IFS= read -r kv; do args+=(--data-urlencode "$kv"); done < <(
      jq -r --arg l "$lad" --arg id "$id" '.[$l].cases[] | select(.id == $id) | .params | del(.uprn)
        | to_entries[] | select(.value != "" and .value != null) | "\(.key)=\(.value)"' "$CASES")
    resp="$(get --get "${args[@]}" "$API/lookup/$uprn" 2>&1)" || resp=""
    n="$(printf '%s' "$resp" | jq '.collections | length' 2>/dev/null || echo 0)"
    if [ "${n:-0}" -ge 1 ]; then
      pass "lookup ($label): $module $lad case $id -> $n collections (first: $(printf '%s' "$resp" | jq -r '.collections[0] | "\(.date) \(.type)"'))"
      printf '%s\n' "$uprn" >"$TMP/uprn.$label"; printf '%s\n' "${args[@]}" >"$TMP/args.$label"
      return
    fi
    [ "$tried" -ge 3 ] || continue
    break
  done < <(jq -r --arg l "$lad" '.[$l].cases | sort_by(.source != "sampled") | .[].id' "$CASES")
  fail "lookup ($label): $module $lad, $tried cases tried, none returned collections (last: $(printf '%s' "$resp" | head -c 200))"
}
lookup_module curl_cffi "$CURL_MODULE"
lookup_module pdf "$PDF_MODULE"
lookup_module httpx "$HTTPX_MODULE"

# --- static file -----------------------------------------------------------------------
code="$(get -o /dev/null -w '%{http_code}' "$BASE/static/favicon.svg")"
check "static /static/favicon.svg -> $code" test "$code" = 200

# --- calendar for the plain-httpx case (its lookup above cached it) ---------------------
if [ -f "$TMP/uprn.httpx" ]; then
  cargs=()
  while IFS= read -r a; do cargs+=("$a"); done <"$TMP/args.httpx"
  uprn="$(cat "$TMP/uprn.httpx")"
  ctype="$(get --get "${cargs[@]}" -o /dev/null -w '%{http_code} %{content_type}' "$API/calendar/$uprn")"
  case "$ctype" in
    "200 text/calendar"*) pass "calendar/$uprn -> $ctype" ;;
    *) fail "calendar/$uprn -> $ctype (want 200 text/calendar)" ;;
  esac
else
  fail "calendar: skipped, the httpx lookup did not succeed"
fi

echo
if [ "$FAILS" -eq 0 ]; then echo "spike: all checks passed"; else echo "spike: $FAILS check(s) FAILED"; fi
[ "$FAILS" -eq 0 ]
