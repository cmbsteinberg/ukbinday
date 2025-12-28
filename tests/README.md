# Tests

This directory contains integration tests for the UK Bin Lookup project.

## Test Files

### test_council_lookups.py

Integration tests for the Python bin lookup runtime against actual council APIs.

**Requirements:**
- Python 3.x
- Dependencies from project requirements

**Usage:**
```bash
# Run all tests
python tests/test_council_lookups.py

# Test first 10 councils
python tests/test_council_lookups.py --max 10

# Test specific councils
python tests/test_council_lookups.py --council SwanseaCouncil --council CardiffCouncil

# Save results to JSON
python tests/test_council_lookups.py --save-results results.json

# Adjust concurrency (default: 50)
python tests/test_council_lookups.py --concurrency 10
```

### test_bins_website.js

Integration tests for the bins-website JavaScript application.

**Requirements:**
- Node.js

**Usage:**
```bash
# Run all tests (via npm)
npm run test:website

# Run all tests (direct)
node tests/test_bins_website.js

# Test first 10 councils
node tests/test_bins_website.js --max 10

# Test specific councils
node tests/test_bins_website.js --council SwanseaCouncil --council CardiffCouncil

# Save results to JSON
node tests/test_bins_website.js --save-results results.json

# Show help
node tests/test_bins_website.js --help
```

## What's Tested

### Python Tests (test_council_lookups.py)
- Makes actual HTTP requests to council APIs
- Validates response status codes
- Tests with real council parameters from `extraction/data/input.json`
- Concurrent execution with configurable concurrency
- Reports success rates and error types

### JavaScript Tests (test_bins_website.js)
- **Utility Functions:**
  - Postcode validation (`validatePostcode`)
  - Postcode normalization (`normalizePostcode`)
  - Address normalization (`normalizeAddress`)
  - Council name normalization (`normalizeCouncilName`)

- **Request Building:**
  - URL template filling with parameters
  - HTTP method validation
  - Header construction
  - Body formatting for POST requests
  - Tests using real council configs from `bins-website/data/councils-data.json`

## Test Data Sources

- **Python tests:** Uses `extraction/data/input.json` for test parameters
- **JavaScript tests:** Uses `bins-website/data/councils-data.json` for test parameters

Both test suites validate that council configurations are correctly structured and contain the necessary data for making API requests.
