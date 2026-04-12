# Battle Testing

Scripts for stress-testing and validating the deployed API on Hetzner.

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
| `rate_limit.sh` | Hammers a single endpoint to verify Redis rate limiting returns 429s |
| `chaos.sh` | Kills Redis/restarts containers mid-traffic to test resilience |
| `security.sh` | Basic security checks: headers, error leakage, injection attempts |

## Usage

All scripts take the base URL as the first argument (defaults to `https://bincollection.co.uk`):

```bash
# Run against production
./tests/battletest/smoke.sh
./tests/battletest/load.sh https://bincollection.co.uk

# Run against local Docker stack
./tests/battletest/smoke.sh http://localhost:8000
```

## Running order

1. **`smoke.sh`** — confirm everything is up and responding correctly
2. **`rate_limit.sh`** — confirm Redis rate limiting works before you load test
3. **`load.sh`** or **`k6_load.js`** — stress test (pick one, k6 is more thorough)
4. **`chaos.sh`** — resilience under failure (run while load test is active for max coverage)
5. **`security.sh`** — check for leaky error pages and missing headers

## Memory budget (CX33 = 8GB)

`docker-compose.yml` sets `mem_limit` on each service to prevent OOM kills:

| Service | Limit | Notes |
|---|---|---|
| api | 4GB | Bulk of the headroom — scrapers do network I/O + parsing |
| redis | 512MB | Matches `--maxmemory 512mb` in redis config |
| caddy | 512MB | Reverse proxy, minimal usage |
| goaccess | 256MB | Log parser, steady-state ~50MB |
| uptime-kuma | 512MB | Monitoring dashboard |
| **Total** | **~5.75GB** | Leaves ~2GB for the OS, buffers, and spikes |

If you see OOM kills in `dmesg` or containers restarting, check `docker stats` and adjust limits.

## What to watch during tests

SSH into the Hetzner box and monitor:

```bash
docker stats                              # per-container CPU/memory
docker compose logs -f api --since 1m     # live API logs
docker compose exec redis redis-cli info memory   # Redis memory usage
free -h                                   # host memory (watch for swap)
dmesg | tail -20                          # OOM killer activity
```
