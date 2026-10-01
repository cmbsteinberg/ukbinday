# Moving off Hetzner: Vercel + Cloudflare

Status: plan, 2026-10-01. Nothing is built yet.

## Why

Hetzner raised cloud prices twice in 2026 (April, up to 37%; June, CX/CAX about 33-40%,
CPX/CCX 2-3x). Existing servers keep their old price until they're resized or reordered,
so this isn't urgent, but the box also carries six containers (API, worker, Redis,
Caddy, GoAccess, Uptime Kuma) that someone has to keep patched. The load fits
comfortably in free tiers. The project is non-commercial, so Vercel Hobby is allowed.

## Target

```
user / calendar app
        │
        ▼
Cloudflare (free): DNS, proxy, cache rule on /api/v1/calendar/*      ← added in phase 5
        │ cache miss
        ▼
Vercel Hobby, region lhr1 (London): the FastAPI app as it is today
        │                                     ▲
        │ get/put {uprn}.ics + {uprn}.json    │ daily crons → /api/v1/internal/refresh
        ▼                                     │
Cloudflare R2 (free): the ICS cache
```

What goes away: the Hetzner box, `docker-compose.yml`'s `worker`, `redis`, `caddy`,
`goaccess` and `uptime-kuma` services, `Caddyfile`, `goaccess.conf`, and the SSH deploy.
The `Dockerfile` stays, for local runs and as the escape hatch to Cloud Run.

What doesn't change: the scrapers, the registry, every public route and query key.
Calendar URLs already in people's calendars (`https://ukbinday.co.uk/api/v1/calendar/...`)
keep working, because the domain stays the same.

## Sizing (measured)

One real case per council module, 346 modules, run one at a time per process
(`/tmp/cpu_probe.py`, 2026-10-01, M-series Mac):

| | mean | p50 | p90 | p99 | max |
|---|---|---|---|---|---|
| CPU per scrape | 35 ms | 22 ms | 55 ms | 321 ms | 876 ms (Trafford, PDF) |
| Wall time per scrape | 1.8 s | 0.9 s | 3.9 s | 12.5 s | 22 s |

- Importing all 348 council modules takes 0.24 s of CPU. `ScraperRegistry.build()`,
  including the old `api/scrapers/`, takes 0.54 s. Peak RSS was 63-134 MB.
- Budget below uses **70 ms per scrape**, double the measured mean, for slower cloud vCPUs.

The refresh job only re-scrapes a UPRN once its `next_collection` is tomorrow or earlier
(`RefreshJob._eligible`). So each calendar costs about one scrape per collection cycle,
not one per night, plus daily retries while a council is failing (up to
`ICS_FAILURE_THRESHOLD` = 14).

| | 100 calendars (today) | 10,000 calendars |
|---|---|---|
| Refresh scrapes/month (weekly cycle) | ~430 | ~43,000 |
| Refresh CPU/month at 70 ms | ~30 s | ~0.85 h |
| Calendar polls/month (~3 per calendar per day) | ~9,000 | ~900,000 |
| R2 storage | < 1 MB | tens of MB |

Hobby limits that matter: 1M function invocations, 1M CDN requests, 4 active CPU-hours
(I/O wait isn't counted), 360 GB-hours of provisioned memory, 300 s max duration,
daily-only crons. **Going over pauses the feature until the 30-day window resets; it
doesn't bill.** That's why calendar polls go through Cloudflare's cache before 10k
calendars. Uncached, 900k polls would sit right at the 1M request cap.

R2 free tier: 10 GB, 1M Class A ops (writes, lists), 10M Class B ops (reads) a month,
no egress fees. A daily refresh pass at 10k calendars is ~10 list calls + 10k sidecar
reads, about 300k reads a month.

## Phases

Each phase ships on its own and leaves the system working. Phases 1-2 run on Hetzner
first, so the risky part (storage) is proven before anything moves.

### Phase 0: spike (do first, throw away)

Deploy the current app, unchanged, to a Vercel preview with Turnstile and Redis unset,
and answer these questions before writing any code. Anything that fails here changes the plan.

1. **Entrypoint.** Vercel only auto-detects `app.py`, `main.py`, `index.py`, ... at the
   root or under `src/` / `app/`, so ours is set explicitly in `pyproject.toml`:

   ```toml
   [tool.vercel]
   entrypoint = "api.main:app"
   ```

   The whole app becomes one function. The old "every file under `/api` is a function"
   convention doesn't apply: in Vercel's builder detection (`vercel/vercel`,
   `packages/fs-detectors/src/detect-builders.ts`), the FastAPI preset lists
   `@vercel/python` in `ignoreRuntimes`, which drops the `api/**/*.py` matches. The preset
   is detected because `pyproject.toml` contains `fastapi`; pin it with
   `"framework": "fastapi"` in `vercel.json` anyway, since falling back to the "Other"
   preset would turn every `api/*.py` that defines `app` or `handler` into its own function.
2. **Lifespan** is supported (Vercel docs, FastAPI page): the registry, `CouncilLookup`
   and `IcsCache` setup in `api/main.py` runs as is. Shutdown cleanup gets at most 500 ms,
   which only matters for closing the curl_cffi session and duckdb, both safe to drop.
   Confirm the cold start time.
3. **Bundle size** under the 500 MB Python limit. See "Dependencies" below.
4. **Native wheels**: duckdb, curl_cffi, lxml, pypdfium2 import and work on Vercel's Linux.
5. **Region** `lhr1` is applied (check the response headers), and the cold start time.
6. `/api/v1/lookup/{uprn}` returns collections for a handful of councils, including one
   `Transport.CURL_CFFI` module and one PDF module.

### Phase 1: ICS cache to R2 (still on Hetzner)

The only real code change. All file I/O is in `api/services/ics_cache.py`, inside sync
methods already run through `asyncio.to_thread`: `_read_sync`, `_read_ics_bytes_sync`,
`_load_ics`, `_atomic_write`, `_write_sync`, `_record_failure_sync`, `iter_entries`,
`_delete_sync`, `count_entries`.

- Replace the direct `Path` calls with a small blob store: `get(key) -> bytes | None`,
  `put(key, data)`, `delete(key)`, `keys(prefix)`. Two implementations: a local directory,
  for dev and tests (what `conftest.py`'s temp `DATA_DIR` uses today), and R2 via the S3
  API (`boto3` with `endpoint_url=https://<account>.r2.cloudflarestorage.com`; sync is
  fine because callers are already on worker threads). Pick by env: `R2_BUCKET` set means R2.
- Keys stay `calendars/{uprn}.ics` and `calendars/{uprn}.json`. A single S3 PUT is atomic,
  so `_atomic_write`'s tmp-and-rename goes away. Keep the existing write order: ICS
  first, sidecar last, so a reader never sees a sidecar pointing at a missing calendar.
- Move the worker heartbeat (`DATA_DIR/.worker_heartbeat`) to `meta/refresh_heartbeat.json`
  in the same store, and add `entries` to it. `/api/v1/metrics` then reads the heartbeat
  instead of `app.state.refresh_job` (there is no long-lived job object on Vercel) and
  instead of `count_entries()` (a bucket list on every metrics scrape).
- Concurrency: `IcsCache`'s per-UPRN `asyncio.Lock` protects only within one instance.
  Two Vercel instances writing the same UPRN at once would race the read-merge-write, and
  the last writer wins. The next refresh repairs it, since writes merge on stable UIDs. At
  this traffic that's acceptable. If it ever isn't, R2 supports conditional PUT
  (`If-Match` on the sidecar's ETag).
- Copy the existing cache: `rclone sync /var/lib/docker/volumes/bins_data/_data/calendars r2:bins/calendars`.
  The store is recoverable anyway: every calendar URL carries `council`, `postcode` and
  `address`, so a lost object is rebuilt on its next poll (only past events are lost).
- Tests: `tests/test_scrape_cache.py` runs against the local store unchanged. Add one
  test for the R2 implementation against a stub S3 server (moto), or skip it if
  credentials aren't set.

Ship it on Hetzner with `R2_*` env vars set. From here on, Hetzner and Vercel can both
serve from the same bucket, which is what makes cutover and rollback a DNS change.

### Phase 2: refresh as an HTTP endpoint

Vercel has no long-running process, so `RefreshJob.run_forever` and the `worker` service
become a cron-triggered route.

- `GET /api/v1/internal/refresh?shard=i&of=n`, rejected unless
  `Authorization: Bearer $CRON_SECRET` matches. Vercel sends that header on cron
  invocations when `CRON_SECRET` is set. Exclude it from the OpenAPI schema.
- `RefreshJob.run_once` gains `shard`, `of` and a `deadline`: take only UPRNs where
  `int(uprn) % of == shard`, stop queueing new work at ~250 s so the run finishes inside
  Vercel's 300 s limit, and leave the rest for the next day. Unfinished UPRNs stay
  eligible, so nothing is lost; they're just a day late.
- Shard count: at 10k calendars ~1,500 UPRNs are due on a given day; at 1.8 s wall each
  and `ICS_REFRESH_CONCURRENCY` raised to 8, that's ~340 s, so 4 shards with headroom.
  Today 1 shard is enough. Crons in `vercel.json`, spread across the night (Hobby fires
  anywhere within the hour):

  ```json
  {
    "framework": "fastapi",
    "regions": ["lhr1"],
    "functions": { "api/main.py": { "maxDuration": 300 } },
    "crons": [
      { "path": "/api/v1/internal/refresh?shard=0&of=4", "schedule": "0 1 * * *" },
      { "path": "/api/v1/internal/refresh?shard=1&of=4", "schedule": "0 2 * * *" },
      { "path": "/api/v1/internal/refresh?shard=2&of=4", "schedule": "0 3 * * *" },
      { "path": "/api/v1/internal/refresh?shard=3&of=4", "schedule": "0 4 * * *" }
    ]
  }
  ```

  The `functions` key depends on the entrypoint chosen in phase 0.
- Keep `python -m api.services.refresh_job` working (it calls `run_once` with one shard
  and no deadline) so Hetzner keeps refreshing until cutover.

### Phase 3: make the app serverless-friendly

Small changes, each independent:

- **Redis becomes optional in practice, not just in code.** Without `REDIS_URL`:
  - `scrape_lock.acquire` already returns `True`. Cross-instance coalescing is lost; see the
    concurrency note in phase 1.
  - `rate_limit` is already a no-op. `/addresses` (the costly route, which calls the paid address
    API) stays behind Turnstile. Add a Cloudflare rate-limiting rule on `/api/*` in
    phase 5 to replace the per-IP hourly limit.
  - The `api:request_counts` analytics hash and `/status`'s `redis_connected` fall away.
    Cloudflare and Vercel analytics replace GoAccess.
  - If any of these turn out to matter, Upstash Redis has a free tier and the existing code
    works with it unchanged via `REDIS_URL`.
- **Scraper health** (`registry.record_success/failure`, shown on `/councils` and
  `/metrics`) is in-memory per instance, so on Vercel it resets on every cold start. That's
  harmless, but don't treat it as meaningful there. The live test and the `working` flags
  are the real source of truth.
- **Static files**: Vercel promotes `app.mount("/static", StaticFiles(...))` to its CDN at
  build time, but keeps them in the function when there's top-level middleware, which
  `api/main.py` has (`log_requests`). Set `[tool.vercel.fastapi.static] cdn = true` to
  promote anyway; static responses then skip the security headers `log_requests` adds,
  which can be set in `vercel.json` `headers` instead.
- **Logs**: JSON to stdout already. Hobby keeps runtime logs for 1 hour, so anything
  you'd want to look back on (refresh stats) goes in the heartbeat object.

### Phase 4: deploy pipeline and council probe

- **Dependencies.** `playwright` (130 MB), `pytest`, `pytest-asyncio` and `ty` moved to
  the `dev` group (done 2026-10-01). Add `boto3`. What's left (duckdb ~39 MB, lxml, cryptography, pdfminer,
  curl_cffi, pypdfium2, boto3, ...) should be ~200 MB, inside the 500 MB Python limit.
  Exclude `pipeline/`, `tests/`, `scripts/`, `api/scrapers/__pycache__` and the
  committed ONS parquets in `pipeline/data/` (~100 MB) from the function bundle. Only
  `api/data/postcode_lookup.parquet` (15 MB) and `lad_lookup.json` are needed at runtime.
- **CI.** `deploy.yml`: keep the `smoke-test` job; replace the SSH step with
  `vercel deploy --prebuilt --prod` using a `VERCEL_TOKEN` secret, and turn off Vercel's
  automatic Git deploys so a failing smoke test still blocks production.
- **Env vars** in Vercel (production): `ADDRESS_API_URL`, `ADDRESS_API_COMPANY_ID`,
  `TURNSTILE_SITE_KEY`, `TURNSTILE_SECRET`, `BASE_URL`, `CORS_ORIGINS`, `R2_ACCOUNT_ID`,
  `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET`, `CRON_SECRET`, `ENV=production`,
  `LOG_FORMAT=json`, `SCRAPER_TIMEOUT=30`, `ICS_REFRESH_CONCURRENCY=8`. Not
  `RUN_REFRESH_JOB` (set it to `0`; the background task can't run there) and not `REDIS_URL`.
- **Council probe.** Requests now leave from AWS London instead of Hetzner, and a council
  that blocks AWS ranges would break silently. Before cutover, run the sampled cases from
  `tests/lad_test_cases.json` against a preview deployment's `/api/v1/lookup/{uprn}`
  (a short script; leave `TURNSTILE_SECRET` unset on the preview) and diff the outcomes
  against `tests/output/lad_integration_output.json`. Councils that pass locally but fail
  from Vercel are the list to deal with. Small numbers can be left on a `NeedsBrowser`
  deeplink; a large number means going to Cloud Run (europe-west2) instead, with the same image.

### Phase 5: cutover

1. Move `ukbinday.co.uk` nameservers to Cloudflare (if they aren't already), records
   unproxied, TTL 60 s, still pointing at Hetzner.
2. Add the domain to the Vercel project, point the records at Vercel, and turn on the
   Cloudflare proxy. Cloudflare SSL mode is "Full (strict)".
3. Cloudflare rules:
   - Cache rule: `/api/v1/calendar/*`, eligible for cache, edge TTL 6 h, cache key includes
     the query string (the default). Only 200s are cached, so a 503 isn't pinned.
   - Cache rule: `/static/*`, edge TTL 1 day.
   - Rate-limiting rule on `/api/*`, per IP, to replace `RATE_LIMIT_HOURLY`.
4. Watch for a few days: Vercel usage (invocations, active CPU), the refresh heartbeat,
   Cloudflare cache hit ratio on calendars, and a calendar subscription that actually updates.
5. Rollback is a DNS change back to Hetzner. Both serve from the same R2 bucket, so no
   data moves either way. Keep the box for two weeks.

### Phase 6: decommission

- Delete the Hetzner server and the `SERVER_HOST` / `SSH_PRIVATE_KEY` secrets.
- Remove `Caddyfile`, `goaccess.conf`, and the `redis`, `caddy`, `goaccess`, `uptime-kuma`
  and `worker` services from `docker-compose.yml` (keep `api` for local use).
  `tests/test_deploy.py` and `tests/test_deploy_docker.sh` shrink to match.
- Replace Uptime Kuma with any free external monitor on `/api/v1/status`.
- Update `AGENTS.md` (Infrastructure, CI/CD, `ics_cache`, `refresh_job`, `scrape_lock`).

## Watch points

| Signal | Means | Action |
|---|---|---|
| Vercel active CPU approaching 4 h/month | Refresh volume or polls reaching the function | Check calendar cache hit ratio; raise `ICS_REFRESH_MIN_AGE_HOURS` |
| Function invocations approaching 1M/month | Cache rule not covering calendars, or real growth | Fix the rule, else move compute to Cloud Run |
| Refresh heartbeat shows unfinished shards | Shards too big for 300 s | Add a shard (another cron entry) |
| A council fails only from Vercel | AWS IP ranges blocked | `NeedsBrowser` deeplink, or Cloud Run for the lot |

Outgrowing Hobby means moving the same container to Cloud Run (request-billed, overage in
pennies), not Vercel Pro ($20 per seat a month). Nothing in this plan ties the code to Vercel
beyond `vercel.json` and the cron auth header.
