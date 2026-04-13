# UK Waste Collection Lookup Service — Spec

## Overview

A web service that lets any UK household look up their waste/bin collection schedule by entering their postcode. The service wraps the 239 `*_gov_uk.py` scrapers from [hacs_waste_collection_schedule](https://github.com/mampfes/hacs_waste_collection_schedule) behind an async API with aggressive caching. src/api/ contains files for the fastapi api

---

## User Flow

```
1. User visits website
2. User enters postcode (e.g. "BR8 7RE")
3. Client-side: Returns list of addresses with UPRNs, local authority code, etc.
4. User selects their address from the list
5. Client-side: POST to our API with { uprn, council_id }
6. Server: checks cache → if miss, runs the relevant council scraper → caches → returns
7. User sees their upcoming bin collection dates
```


---

## Architecture

```
                 Cloudflare (edge cache, DDoS, free tier)
                              │
                         ┌────┴────┐
                         │  Caddy  │  (auto-TLS via Let's Encrypt)
                         └────┬────┘
                              │
                    ┌─────────┴──────────┐
                    │     FastAPI         │
                    │  (async, uvicorn)   │
                    └─────────┬──────────┘
                              │
              ┌───────────────┼───────────────┐
              │               │               │
         Cache hit       Coalesce        Queue miss
         (instant)    (wait on same     (rate-limited
                       in-flight req)    outbound fetch)
              │               │               │
              └───────────────┼───────────────┘
                              │
                    ┌─────────┴──────────┐
                    │       Redis        │
                    │  (cache + queue)   │
                    └────────────────────┘
```

### Components

| Component | Technology | Purpose |
|-----------|-----------|---------|
| Reverse proxy | Caddy 2 (Alpine) | Auto-TLS, reverse proxy to FastAPI |
| CDN | Cloudflare free tier | Edge caching, DDoS protection |
| API server | FastAPI + uvicorn | Async request handling |
| Cache/store | Redis 7 (Alpine) | UPRN→schedule cache, request coalescing, rate limit state |
| Scraper pool | Patched `*_gov_uk.py` modules | Async council scrapers |
| Background worker | Built-in to FastAPI (or separate process) | Overnight cache warming |

---


## Caching Strategy

### Two-tier cache

| Tier | Key | TTL | Purpose |
|------|-----|-----|---------|
| Schedule cache | `schedule:{council}:{uprn}` | 7 days | Scraped collection data |
| HTTP response cache | `Cache-Control` headers | 6 hours | Browser/CDN caching |

### Request coalescing

When multiple users request the same uncached UPRN simultaneously:

```python
# Pseudocode
async def get_schedule(council, uprn):
    # Check cache
    cached = await redis.get(f"schedule:{council}:{uprn}")
    if cached:
        return json.loads(cached)

    # Check if already being fetched (coalesce)
    lock_key = f"fetching:{council}:{uprn}"
    if await redis.exists(lock_key):
        # Wait for the in-flight request to complete
        return await wait_for_result(council, uprn, timeout=30)

    # Mark as fetching, then scrape
    await redis.set(lock_key, "1", ex=60)
    try:
        result = await scrape(council, uprn)
        await redis.set(f"schedule:{council}:{uprn}", json.dumps(result), ex=604800)
        await redis.publish(f"result:{council}:{uprn}", json.dumps(result))
        return result
    finally:
        await redis.delete(lock_key)
```

### Per-council rate limiting

Outbound scrape requests are rate-limited per council to avoid getting blocked:

- Max 5 concurrent outbound requests per council
- 500ms minimum gap between requests to the same council domain
- Implemented via Redis semaphore per council

If the queue is deep (>50 waiting), return a `202 Accepted` with a `Retry-After: 30` header instead of holding connections open indefinitely.

### Cache warming (background)

A nightly job (e.g. 2-4 AM) re-scrapes all UPRNs that were accessed in the last 30 days:

- Query Redis for all `schedule:*` keys with TTL < 2 days
- Re-scrape at a polite rate: 2 req/s per council, spread over hours
- This ensures returning users always get cache hits


## Deployment

### Infrastructure

Single Hetzner VPS: **CPX21** (3 vCPU / 4GB RAM / 80GB SSD) — €8.50/mo.

### Docker Compose

```yaml
services:
  api:
    build: .
    ports:
      - "8000:8000"
    depends_on:
      - redis
    environment:
      - REDIS_URL=redis://redis:6379
    restart: always

  redis:
    image: redis:7-alpine
    volumes:
      - redis_data:/data
    command: redis-server --save 60 1 --loglevel warning
    restart: always

  caddy:
    image: caddy:2-alpine
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./Caddyfile:/etc/caddy/Caddyfile
      - caddy_data:/data
    restart: always

volumes:
  redis_data:
  caddy_data:
```

### Caddyfile

```
ukbinday.co.uk {
    reverse_proxy api:8000
}
```

### Dockerfile (API)

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN pip install uv && uv sync --frozen
COPY . .
CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### Deployment workflow

```bash
# First time
ssh root@<hetzner-ip>
curl -fsSL https://get.docker.com | sh
git clone https://github.com/you/waste-lookup.git
cd waste-lookup
docker compose up -d

# Updates (on push to main, via GitHub Action or manual)
ssh root@<hetzner-ip>
cd waste-lookup && git pull && docker compose up -d --build api
```

---

## Monitoring

### Uptime Kuma (self-hosted)

```yaml
  uptime-kuma:
    image: louislam/uptime-kuma:1
    ports:
      - "3001:3001"
    volumes:
      - uptime_data:/data
    restart: always
```

Monitors:
- `/api/health` endpoint — overall API health
- Per-council scraper success rate (logged to Redis, exposed via `/api/health`)
- Alert via Telegram/email when a council's scraper fails >3 times consecutively

### Logging

Structured JSON logs from FastAPI, including:
- Council, UPRN, cache hit/miss, response time, upstream status code
- Aggregated per-council error rates

---

## Cost Summary

| Item | Cost |
|------|------|
| Hetzner CPX21 | €8.50/mo |
| Domain | ~£10/yr |
| Cloudflare DNS + CDN | Free |
| postcodes.io | Free |
| **Total** | **~£10/mo** |

---

## Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Council site changes break scraper | One council stops working | Per-council health monitoring; track upstream HACS repo for fixes; community maintains these |
| Launch spike overwhelms council sites | Rate-limited/blocked | Request coalescing, per-council rate limits, queue with backpressure (202 Accepted) |
| Council blocks our IP | One council stops working | Polite rate limiting + User-Agent; add residential proxy for problem councils (~$10-15/mo if needed) |
| Upstream HACS repo changes structure | Sync breaks | Pin to known-good commit; daily CI checks for breaking changes |
| Legal/ToS issues | Cease and desist from a council | All data is public; UK public sector info reuse is generally permitted; respond to individual council requests |
| Redis data loss | Cache cold-starts | Redis persistence (RDB snapshots); worst case is a few hours of cache misses |


**Tiers (by IP behaviour, not authentication):**

| Consumer | Limit | Rationale |
|----------|-------|-----------|
| Normal user (browser) | 30 req/day per IP | Nobody checks bins more than a few times a week |
| Power user / small app | 30 req/day per IP | Same limit — sufficient for personal automations |
| Abusive scraper | Blocked via Cloudflare | Auto-detected by rate + pattern |

**Why 30/day is enough:**
- A household checks once, maybe twice a week
- An app integrating for one address needs 1 req/day (cached for 7 days, so even less)
- Anyone needing more is either scraping or running a service on top — they can talk to us

**Burst protection:**
- Additionally cap at 5 req/minute per IP to prevent hammering
- Return `429` with `Retry-After` header

**Cloudflare layer:**
- Cloudflare's free tier includes basic bot detection and rate limiting rules
- Add a Cloudflare WAF rule: block IPs that exceed 100 req/hour
- This catches abuse before it hits your server

### Response headers

Every API response includes:

```
X-RateLimit-Limit: 30
X-RateLimit-Remaining: 27
X-RateLimit-Reset: 2026-03-21T00:00:00Z
Cache-Control: public, max-age=21600  # 6 hours
```

This lets consumers self-regulate and cache on their end.

### CORS

Wide open — public API, no secrets:

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)
```
