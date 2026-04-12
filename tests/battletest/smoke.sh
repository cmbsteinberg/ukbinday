#!/usr/bin/env bash
# Smoke test — hit every major endpoint once and validate responses.
set -euo pipefail

BASE="${1:-https://bincollection.co.uk}"
PASS=0
FAIL=0

check() {
    local label="$1" url="$2" expect_status="${3:-200}" expect_body="${4:-}"
    local status body

    body=$(curl -sS -o /dev/null -w '%{http_code}' --max-time 30 "$url") || true
    status="$body"
    body=$(curl -sS --max-time 30 "$url" 2>/dev/null) || true

    if [[ "$status" != "$expect_status" ]]; then
        echo "FAIL  $label — expected $expect_status, got $status"
        ((FAIL++))
        return
    fi

    if [[ -n "$expect_body" && "$body" != *"$expect_body"* ]]; then
        echo "FAIL  $label — response missing '$expect_body'"
        ((FAIL++))
        return
    fi

    echo "OK    $label ($status)"
    ((PASS++))
}

echo "=== Smoke Test: $BASE ==="
echo

# Landing page
check "Landing page" "$BASE/"  200 "<title>"

# Health / status
check "Health endpoint" "$BASE/api/v1/health" 200
check "System status"   "$BASE/api/v1/status" 200 '"scrapers_loaded"'

# Council list
check "Council list"    "$BASE/api/v1/councils" 200

# Council lookup (real postcode)
check "Council lookup"  "$BASE/api/v1/council/SW1A1AA" 200

# Scraper lookup (known UPRN from test cases — aberdeenshire)
check "Scraper lookup"  "$BASE/api/v1/lookup/000151124612" 200

# Calendar endpoint (should return ical)
check "Calendar (ical)" "$BASE/api/v1/calendar/000151124612" 200 "BEGIN:VCALENDAR"

# Error cases
check "Invalid postcode" "$BASE/api/v1/council/ZZZZZZZ" 404
check "404 route"        "$BASE/api/v1/nonexistent" 404

# Static assets
check "Static JS"        "$BASE/static/app.js" 200

# Metrics
check "Metrics endpoint" "$BASE/api/v1/metrics" 200

echo
echo "=== Results: $PASS passed, $FAIL failed ==="
[[ "$FAIL" -eq 0 ]] || exit 1
