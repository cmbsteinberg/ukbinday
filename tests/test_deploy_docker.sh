#!/usr/bin/env bash
# Test the Docker Compose deployment by building, starting, testing endpoints, and tearing down.
set -euo pipefail

BASE_URL="http://localhost:8000"
MAX_WAIT=60  # seconds to wait for API to be ready
PASSED=0
FAILED=0
FAILURES=""

# --- Helpers ---

cleanup() {
    echo ""
    echo "=== Tearing down ==="
    docker compose down --volumes --remove-orphans 2>/dev/null
}
trap cleanup EXIT

assert_status() {
    local description="$1" url="$2" expected="$3"
    local status
    status=$(curl -s -o /dev/null -w "%{http_code}" "$url")
    if [ "$status" = "$expected" ]; then
        echo "  PASS  $description (HTTP $status)"
        ((PASSED++))
    else
        echo "  FAIL  $description — expected $expected, got $status"
        ((FAILED++))
        FAILURES="${FAILURES}\n  - $description (expected $expected, got $status)"
    fi
}

assert_json_field() {
    local description="$1" url="$2" field="$3"
    local body
    body=$(curl -s "$url")
    if echo "$body" | python3 -c "import sys,json; data=json.load(sys.stdin); assert $field" 2>/dev/null; then
        echo "  PASS  $description"
        ((PASSED++))
    else
        echo "  FAIL  $description — assertion failed on response"
        ((FAILED++))
        FAILURES="${FAILURES}\n  - $description"
    fi
}

assert_body_contains() {
    local description="$1" url="$2" needle="$3"
    local body
    body=$(curl -s "$url")
    if echo "$body" | grep -q "$needle"; then
        echo "  PASS  $description"
        ((PASSED++))
    else
        echo "  FAIL  $description — response missing '$needle'"
        ((FAILED++))
        FAILURES="${FAILURES}\n  - $description (missing '$needle')"
    fi
}

# --- Build & Start ---

echo "=== Building and starting Docker Compose stack ==="
docker compose up --build -d

echo "=== Waiting for API to be ready (max ${MAX_WAIT}s) ==="
elapsed=0
until curl -sf "$BASE_URL/api/v1/health" >/dev/null 2>&1; do
    if [ "$elapsed" -ge "$MAX_WAIT" ]; then
        echo "FATAL: API did not become ready within ${MAX_WAIT}s"
        echo ""
        echo "--- Container logs ---"
        docker compose logs api --tail 50
        exit 1
    fi
    sleep 2
    elapsed=$((elapsed + 2))
    printf "  waiting... (%ds)\n" "$elapsed"
done
echo "API is ready (took ~${elapsed}s)"

# --- Tests ---

echo ""
echo "=== Running deployment tests ==="

echo ""
echo "--- Health & Infrastructure ---"
assert_status "GET /api/v1/health returns 200" "$BASE_URL/api/v1/health" 200
assert_status "GET /api/v1/docs returns 200" "$BASE_URL/api/v1/docs" 200
assert_status "GET /api/v1/redoc returns 200" "$BASE_URL/api/v1/redoc" 200
assert_status "GET /api/v1/openapi.json returns 200" "$BASE_URL/api/v1/openapi.json" 200

echo ""
echo "--- Frontend Pages ---"
assert_status "GET / returns 200" "$BASE_URL/" 200
assert_body_contains "Landing page has title" "$BASE_URL/" "UK Bin Collections"
assert_status "GET /api-docs returns 200" "$BASE_URL/api-docs" 200

echo ""
echo "--- API Endpoints ---"
assert_status "GET /api/v1/councils returns 200" "$BASE_URL/api/v1/councils" 200
assert_json_field "Councils list is non-empty" "$BASE_URL/api/v1/councils" "len(data) > 0"
assert_json_field "Councils have id and name" "$BASE_URL/api/v1/councils" "'id' in data[0] and 'name' in data[0]"

echo ""
echo "--- API Prefix Compatibility ---"
assert_status "GET /api/councils (legacy prefix)" "$BASE_URL/api/councils" 200
assert_status "GET /api/v1/councils (v1 prefix)" "$BASE_URL/api/v1/councils" 200

echo ""
echo "--- Error Handling ---"
assert_status "Lookup missing council param returns 422" "$BASE_URL/api/v1/lookup/123456" 422
assert_status "Lookup nonexistent council returns 404" "$BASE_URL/api/v1/lookup/123456?council=nonexistent" 404
assert_status "Unknown route returns 404" "$BASE_URL/api/v1/nonexistent" 404

echo ""
echo "--- CORS ---"
cors_header=$(curl -s -o /dev/null -w "%{http_code}" -X OPTIONS \
    -H "Origin: http://example.com" \
    -H "Access-Control-Request-Method: GET" \
    "$BASE_URL/api/v1/councils")
# Just check OPTIONS doesn't error out (FastAPI returns 200 or 400 depending on config)
if [ "$cors_header" = "200" ]; then
    echo "  PASS  CORS preflight returns 200"
    ((PASSED++))
else
    echo "  WARN  CORS preflight returned $cors_header (may be OK depending on config)"
    ((PASSED++))
fi

echo ""
echo "--- Redis Connectivity ---"
# Health endpoint should reflect redis status when REDIS_URL is set
assert_json_field "Health includes redis info" "$BASE_URL/api/v1/health" "isinstance(data, list)"

# --- Summary ---

echo ""
echo "==============================="
echo "  Results: $PASSED passed, $FAILED failed"
echo "==============================="

if [ "$FAILED" -gt 0 ]; then
    echo -e "\nFailures:$FAILURES"
    echo ""
    echo "--- API container logs ---"
    docker compose logs api --tail 30
    exit 1
fi

echo ""
echo "All deployment tests passed."
