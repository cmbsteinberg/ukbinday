# Battle Testing

Scripts for stress-testing and validating the deployed API.

## Prerequisites

```bash
# Load testing
brew install hey        # simple HTTP benchmarking
brew install k6         # scriptable load testing (Grafana)

# Security scanning (optional)
brew install nikto
```

## Scripts

| Script | What it does |
|---|---|
| `smoke.sh` | Hits every major endpoint once, checks status codes and response shapes |
| `load.sh` | Burst + sustained load test with `hey` against key endpoints |
| `k6_load.js` | Ramping load test with `k6` — realistic traffic patterns |
| `security.sh` | Basic security checks: headers, error leakage, injection attempts |

## Usage

All scripts take the base URL as the first argument (defaults to `https://ukbinday.co.uk`):

```bash
# Run against production
./tests/battletest/smoke.sh
./tests/battletest/load.sh https://ukbinday.co.uk

# Run against local Docker stack
./tests/battletest/smoke.sh http://localhost:8000
```

## Running order

1. **`smoke.sh`** — confirm everything is up and responding correctly
2. **`load.sh`** or **`k6_load.js`** — stress test (pick one, k6 is more thorough)
3. **`security.sh`** — check for leaky error pages and missing headers
