#!/usr/bin/env bash
# Basic security checks — headers, error leakage, injection attempts.
set -euo pipefail

BASE="${1:-https://bincollection.co.uk}"
PASS=0
FAIL=0
WARN=0

check() {
    local label="$1" result="$2"
    if [[ "$result" == "pass" ]]; then
        echo "OK    $label"
        ((PASS++))
    elif [[ "$result" == "warn" ]]; then
        echo "WARN  $label"
        ((WARN++))
    else
        echo "FAIL  $label"
        ((FAIL++))
    fi
}

echo "=== Security Check: $BASE ==="
echo

# --- Response Headers ---
echo "--- Response Headers ---"
headers=$(curl -sS -D - -o /dev/null --max-time 10 "$BASE/" 2>/dev/null)

# Check for server version leakage
if echo "$headers" | grep -qi "^server:.*caddy"; then
    check "Server header reveals Caddy (minor)" "warn"
else
    check "Server header not leaking" "pass"
fi

# HTTPS redirect (only if testing against HTTPS URL)
if [[ "$BASE" == https://* ]]; then
    http_url="${BASE/https/http}"
    redirect_status=$(curl -sS -o /dev/null -w '%{http_code}' --max-time 10 -L "$http_url" 2>/dev/null)
    if [[ "$redirect_status" == "200" ]]; then
        check "HTTP → HTTPS redirect works" "pass"
    else
        check "HTTP → HTTPS redirect (status: $redirect_status)" "warn"
    fi
fi
echo

# --- Error Response Leakage ---
echo "--- Error Response Leakage ---"

# 404 should not reveal stack traces
body_404=$(curl -sS --max-time 10 "$BASE/api/v1/nonexistent" 2>/dev/null)
if echo "$body_404" | grep -qiE "traceback|File \"|at line|stacktrace"; then
    check "404 leaks stack trace" "fail"
else
    check "404 response is clean" "pass"
fi

# Force an error with bad params — should not leak internals
body_err=$(curl -sS --max-time 10 "$BASE/api/v1/lookup/'; DROP TABLE--" 2>/dev/null)
if echo "$body_err" | grep -qiE "traceback|File \"|internal server|stacktrace"; then
    check "Error response leaks internals" "fail"
else
    check "Error responses are clean" "pass"
fi
echo

# --- Input Injection Attempts ---
echo "--- Injection Attempts ---"

# Path traversal
status_traversal=$(curl -sS -o /dev/null -w '%{http_code}' --max-time 10 "$BASE/api/v1/council/..%2F..%2Fetc%2Fpasswd" 2>/dev/null)
if [[ "$status_traversal" =~ ^(400|404|422)$ ]]; then
    check "Path traversal rejected ($status_traversal)" "pass"
else
    check "Path traversal returned $status_traversal" "warn"
fi

# Script injection in postcode
body_xss=$(curl -sS --max-time 10 "$BASE/api/v1/council/<script>alert(1)</script>" 2>/dev/null)
if echo "$body_xss" | grep -q "<script>"; then
    check "XSS reflected in response" "fail"
else
    check "XSS not reflected in response" "pass"
fi

# Oversized input
status_large=$(curl -sS -o /dev/null -w '%{http_code}' --max-time 10 "$BASE/api/v1/council/$(python3 -c "print('A'*10000)")" 2>/dev/null)
if [[ "$status_large" =~ ^(400|404|414|422)$ ]]; then
    check "Oversized input rejected ($status_large)" "pass"
else
    check "Oversized input returned $status_large" "warn"
fi

# Null bytes
status_null=$(curl -sS -o /dev/null -w '%{http_code}' --max-time 10 "$BASE/api/v1/council/SW1A%001AA" 2>/dev/null)
if [[ "$status_null" =~ ^(400|404|422)$ ]]; then
    check "Null byte rejected ($status_null)" "pass"
else
    check "Null byte returned $status_null" "warn"
fi
echo

# --- CORS ---
echo "--- CORS ---"
cors_headers=$(curl -sS -D - -o /dev/null --max-time 10 \
    -H "Origin: https://evil.example.com" \
    "$BASE/api/v1/status" 2>/dev/null)

if echo "$cors_headers" | grep -qi "access-control-allow-origin: https://evil.example.com"; then
    check "CORS allows arbitrary origins" "fail"
elif echo "$cors_headers" | grep -qi "access-control-allow-origin: \*"; then
    check "CORS allows wildcard origin (may be intentional)" "warn"
else
    check "CORS does not reflect arbitrary origin" "pass"
fi
echo

echo "=== Results: $PASS passed, $FAIL failed, $WARN warnings ==="
[[ "$FAIL" -eq 0 ]] || exit 1
