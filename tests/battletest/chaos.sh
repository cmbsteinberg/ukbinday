#!/usr/bin/env bash
# Chaos tests — kill services and verify the API degrades gracefully.
# Run this FROM the Hetzner box (needs docker compose access).
set -euo pipefail

BASE="${1:-http://localhost:8000}"
PASS=0
FAIL=0
WARN=0

check_status() {
    local label="$1" url="$2" expect="$3"
    local status
    status=$(curl -sS -o /dev/null -w '%{http_code}' --max-time 15 "$url" 2>/dev/null) || status="000"
    if [[ "$status" == "$expect" ]]; then
        echo "OK    $label (got $status)"
        ((PASS++))
    else
        echo "FAIL  $label — expected $expect, got $status"
        ((FAIL++))
    fi
}

echo "=== Chaos Test ==="
echo "WARNING: This restarts containers. Run on the deployed box, not locally."
echo

# --- Test 1: Kill Redis ---
echo "--- 1. Kill Redis (rate limiting + caching should degrade gracefully) ---"
docker compose stop redis
sleep 3

check_status "API still responds without Redis" "$BASE/api/v1/status" "200"
check_status "Scraper works without Redis (no cache)" "$BASE/api/v1/lookup/000151124612" "200"

echo "  Restoring Redis..."
docker compose start redis
sleep 5
check_status "API works after Redis restore" "$BASE/api/v1/status" "200"
echo

# --- Test 2: Restart API under load ---
echo "--- 2. Restart API container (tests lifespan/registry reload) ---"
docker compose restart api
sleep 10  # wait for healthcheck

check_status "API healthy after restart" "$BASE/api/v1/status" "200"
check_status "Registry loaded after restart" "$BASE/api/v1/councils" "200"

# Verify scraper count didn't drop
scraper_count=$(curl -sS --max-time 10 "$BASE/api/v1/status" | python3 -c "import sys,json; print(json.load(sys.stdin).get('scrapers_loaded', 0))")
if (( scraper_count > 300 )); then
    echo "OK    Scraper count after restart: $scraper_count"
    ((PASS++))
else
    echo "FAIL  Only $scraper_count scrapers loaded after restart (expected 300+)"
    ((FAIL++))
fi
echo

# --- Test 3: Redis restart (connection pool recovery) ---
echo "--- 3. Restart Redis (tests connection pool reconnection) ---"
docker compose restart redis
sleep 5

check_status "API reconnects to Redis" "$BASE/api/v1/status" "200"

# Verify rate limit headers come back (means Redis connection restored)
headers=$(curl -sS -D - -o /dev/null --max-time 10 "$BASE/api/v1/status" 2>/dev/null)
if echo "$headers" | grep -qi "x-ratelimit"; then
    echo "OK    Rate limit headers present (Redis reconnected)"
    ((PASS++))
else
    echo "WARN  No rate limit headers — Redis may not have reconnected yet"
    # Not a hard fail, might need more time
fi
echo

# --- Test 4: Memory pressure check (CX33 = 8GB total) ---
echo "--- 4. Memory check (8GB budget) ---"
docker stats --no-stream --format "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.MemPerc}}"
echo

# Check total Docker memory usage
total_mb=$(docker stats --no-stream --format '{{.MemUsage}}' | \
    awk -F'/' '{gsub(/[^0-9.]/, "", $1); if($1~/GiB/) {gsub(/GiB/,"",$1); print $1*1024} else {gsub(/MiB/,"",$1); print $1}}' | \
    awk '{s+=$1} END {printf "%.0f", s}')
echo "Total Docker memory: ${total_mb}MB / 8192MB"
if (( total_mb > 6500 )); then
    echo "WARN  Memory usage above 80% of 8GB — risk of OOM under load"
    ((WARN++))
else
    echo "OK    Memory usage within safe range"
    ((PASS++))
fi
echo

# --- Test 5: Host memory ---
echo "--- 5. Host memory ---"
free -h 2>/dev/null || vm_stat 2>/dev/null || echo "(skipped — not Linux)"
echo

echo "=== Results: $PASS passed, $FAIL failed, $WARN warnings ==="
[[ "$FAIL" -eq 0 ]] || exit 1
