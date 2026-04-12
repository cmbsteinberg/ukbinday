#!/usr/bin/env bash
# Load test with `hey` — burst and sustained patterns against key endpoints.
# Requires: brew install hey
set -euo pipefail

BASE="${1:-https://bincollection.co.uk}"

command -v hey >/dev/null || { echo "Install hey: brew install hey"; exit 1; }

echo "=== Load Test: $BASE ==="
echo

# --- Lightweight endpoints (high concurrency) ---

echo "--- Burst: /api/v1/status (200 requests, 50 concurrent) ---"
hey -n 200 -c 50 "$BASE/api/v1/status"
echo

echo "--- Burst: /api/v1/councils (200 requests, 50 concurrent) ---"
hey -n 200 -c 50 "$BASE/api/v1/councils"
echo

# --- Council lookup (moderate — hits address lookup + parquet) ---

echo "--- Sustained: /api/v1/council/{postcode} (100 requests, 20 concurrent) ---"
hey -n 100 -c 20 "$BASE/api/v1/council/SW1A1AA"
echo

# --- Scraper lookup (heavy — actually runs a scraper) ---

echo "--- Scraper: /api/v1/lookup/{uprn} (20 requests, 5 concurrent) ---"
echo "    (This hits a live council site — keep concurrency low)"
hey -n 20 -c 5 -t 60 "$BASE/api/v1/lookup/000151124612"
echo

# --- Mixed postcodes (simulates real diverse traffic) ---

POSTCODES=("SW1A1AA" "EH1+1YZ" "B1+1BB" "LS1+1UR" "CF10+1EP")
echo "--- Mixed postcodes: council lookup (5 postcodes x 10 requests) ---"
for pc in "${POSTCODES[@]}"; do
    echo "  $pc:"
    hey -n 10 -c 5 "$BASE/api/v1/council/$pc" 2>&1 | grep -E "Requests/sec|Average|Status code"
done
echo

echo "=== Load test complete ==="
