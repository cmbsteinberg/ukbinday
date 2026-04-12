#!/usr/bin/env bash
# Verify Redis rate limiting — hammer one endpoint past the daily limit.
# Default RATE_LIMIT_DAILY is 100, so we send 110 requests and expect 429s.
set -euo pipefail

BASE="${1:-https://bincollection.co.uk}"
LIMIT="${2:-100}"
TOTAL=$((LIMIT + 10))

echo "=== Rate Limit Test: $BASE ==="
echo "Sending $TOTAL requests (limit is $LIMIT/day)"
echo

count_200=0
count_429=0
count_other=0
first_429=""

for i in $(seq 1 "$TOTAL"); do
    status=$(curl -sS -o /dev/null -w '%{http_code}' --max-time 10 "$BASE/api/v1/status")
    case "$status" in
        200) ((count_200++)) ;;
        429)
            ((count_429++))
            [[ -z "$first_429" ]] && first_429="$i"
            ;;
        *)  ((count_other++)); echo "  Request $i: unexpected $status" ;;
    esac

    # Print progress every 20 requests
    if (( i % 20 == 0 )); then
        echo "  ... $i/$TOTAL sent (200s: $count_200, 429s: $count_429)"
    fi
done

echo
echo "=== Results ==="
echo "200 responses: $count_200"
echo "429 responses: $count_429"
echo "Other:         $count_other"
[[ -n "$first_429" ]] && echo "First 429 at request: $first_429"

if [[ "$count_429" -gt 0 ]]; then
    echo
    echo "PASS — rate limiting is working"

    # Check Retry-After header on a 429
    echo
    echo "429 response headers:"
    curl -sS -D - -o /dev/null --max-time 10 "$BASE/api/v1/status" 2>/dev/null | grep -iE "retry-after|x-ratelimit"
else
    echo
    echo "FAIL — no 429s received after $TOTAL requests"
    echo "Check that REDIS_URL is set and Redis is running"
    exit 1
fi
