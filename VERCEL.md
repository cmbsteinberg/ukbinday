# Moving off Hetzner: Vercel + Cloudflare

Status: revised 2026-10-01. The tidy-up has landed, and the in-repo work (phases 1-4)
is on `feature/vercel-migration`. What's left is outside the repo: the phase 0 spike,
R2 and Vercel setup, the council probe against a preview, and the cutover.

The modules in `api/councils/` are the only scrapers. `ScraperRegistry.invoke()` has one
path (`api.councils._base.run`), and every outbound request goes through the harness
`Http` (`api/councils/_base/http.py`), so timeouts, transport choice (httpx or curl_cffi)
and TLS settings are in one file. `requests` and `playwright` are no longer dependencies.
`api/scrapers/` and `api/compat/` may still exist locally holding stale `.pyc` files;
they're untracked, and `.vercelignore` keeps them out of a local `vercel build`.

## Done in the repo vs. left to do

| Phase | In the repo | Outside the repo |
|---|---|---|
| 0 spike | `[tool.vercel]` in `pyproject.toml`, `vercel.json` | Deploy a preview and answer the questions below |
| 1 R2 cache | `api/services/blob_store.py`, `IcsCache` on top of it, heartbeat in the store | Create the bucket and keys, `rclone` the Hetzner cache across, set `R2_*` on Hetzner |
| 2 refresh endpoint | `/api/v2/internal/refresh`, sharded `run_once` with a deadline, cron in `vercel.json` | Set `CRON_SECRET` |
| 3 serverless | Nothing needed beyond phase 1; static CDN option and headers in config | — |
| 4 deploy | `deploy-vercel` job in `deploy.yml`, `.vercelignore`, `scripts/vercel_probe.py` | Vercel project, secrets, env vars, run the probe |
| 5 cutover | — | DNS and Cloudflare rules |
| 6 decommission | Deliberately not done, Hetzner being the rollback path until two weeks after cutover. `scripts/vercel/decommission.sh` does it then | Run the script; set up the monitors |

### Scripts for the steps outside the repo

Throwaway scripts in `scripts/vercel/`, each with usage in its header. The Vercel CLI
flags were checked against `vercel <cmd> --help` (CLI 62.1.0) and the CLI docs. None of the
scripts has run against real Vercel or R2 yet.

| Script | Phase | What it does |
|---|---|---|
| `preview.sh` | 0 | `vercel deploy` to a preview, built remotely by Vercel (a local `vercel build` put `.env.local` and other ignored files in the function); prints only the URL, so `URL=$(scripts/vercel/preview.sh)` works. Needs `npx vercel@latest link` once |
| `spike.sh <url>` | 0 | PASS/FAIL checks: cold start, `lhr1` in `x-vercel-id`, `/councils`, `/find`, a `/{lad}/view` each for a curl_cffi, a PDF and a plain httpx council (cases read from `lad_test_cases.json`), a static file, `/{lad}/subscribe` |
| `logs.sh <url>` | 0, 5 | `vercel inspect` plus recent error logs (Hobby keeps an hour) |
| `env.example`, `env_push.sh <file> [production\|preview]` | 4 | Pushes the expected env vars to Vercel (unknown keys rejected, values on stdin, generates `CRON_SECRET` if absent). Vercel stores them as sensitive and won't show them again, so keep your own `CRON_SECRET` if you want to call `refresh_now.sh` |
| `cf_setup.sh <env-file>` | 1 | Cloudflare API: creates the `bins` bucket and a bucket-scoped S3 key, writes `R2_*` into the env file. Needs one dashboard-made `CLOUDFLARE_API_TOKEN` (R2 Edit, API Tokens Edit, DNS Edit on the zone; header lists them) and R2 enabled with a card |
| `hetzner_r2.sh <env-file> [--dry-run\|--sync-only]` | 1 | From your machine over SSH (`HETZNER_HOST`, default `deploy@ukbinday.co.uk`): `rclone sync` of the `bins_data` volume into R2 in a throwaway `rclone/rclone` container, then `R2_*` into the box's `.env` and `docker compose up -d api worker` |
| `github_secrets.sh` | 4 | Prompts for a dashboard-made Vercel token (the CLI login can't mint one) and sets `VERCEL_TOKEN`, `VERCEL_ORG_ID`, `VERCEL_PROJECT_ID` with `gh`, which switches on `deploy-vercel` |
| `cutover.sh [--dry-run\|--rollback <backup>]` | 5 | Checks production health, `vercel domains add` apex + www, saves the current Cloudflare records to `.vercel/dns_backup_<stamp>.json`, then (typed confirmation) apex A and www CNAME to Vercel's recommended values, unproxied, TTL 60, deleting Hetzner's AAAA. `--rollback` restores the backup |
| `refresh_now.sh <url> [shard] [of]` | 2 | Calls `/api/v2/internal/refresh` with `CRON_SECRET`, then prints the heartbeat from `/metrics` |
| `probe.sh <url>` | 4 | Wraps `scripts/vercel_probe.py` |
| `decommission.sh` | 6 | Preflight (production answers from Vercel, refresh heartbeat under 36 h, clean tree), then three typed-confirmation stages: delete the Hetzner server/firewall/SSH key (`hcloud`), delete the SSH deploy secrets (`gh`), and the repo edits (remove Caddy/GoAccess/`scripts/deploy`, cut compose to `api`, drop the SSH job and `hcloud`/`paramiko`). `--dry-run`, `--skip-*`. Repo stage tested on a copy; the others only dry-run |

`VERCEL_BYPASS` (Deployment Protection bypass secret) is honoured by `spike.sh` and
`probe.sh`, if previews are protected.

Order, with the manual steps marked (you):

1. (you) `npx vercel@latest login` and `npx vercel@latest link`; in Cloudflare, enable R2
   and create `CLOUDFLARE_API_TOKEN` (see `cf_setup.sh`); copy `env.example` to
   `/tmp/vercel.env` and fill in the address API and Turnstile values.
2. `preview.sh` → `spike.sh`
3. `cf_setup.sh /tmp/vercel.env` → `hetzner_r2.sh /tmp/vercel.env --dry-run` → `hetzner_r2.sh /tmp/vercel.env`
4. `env_push.sh /tmp/vercel.env preview` and `production` → a fresh `preview.sh` →
   `refresh_now.sh` and `probe.sh` against it
5. `github_secrets.sh`, then push to `main` (first production deploy)
6. `cutover.sh --dry-run` → (you choose when) `cutover.sh`
7. Two weeks later: (you) `decommission.sh`

The domain's DNS is already on Cloudflare (nameservers `byron`/`luciana.ns.cloudflare.com`,
records unproxied, apex A + AAAA and www A on Hetzner, MX on Cloudflare Email Routing,
checked 2026-10-02).

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
Vercel CDN: caches subscribe/download for 12 h (Cache-Control: s-maxage=43200 from the app)
        │ cache miss
        ▼
Vercel Hobby, region lhr1 (London): the FastAPI app as it is today
        │                                     ▲
        │ get/put {uprn}.ics + {uprn}.json    │ daily crons → /api/v2/internal/refresh
        ▼                                     │
Cloudflare R2 (free): the ICS cache
```

Cloudflare is only the storage account. DNS can stay with the current registrar,
pointed at Vercel; Cloudflare's proxy and rate-limit rule are an optional later step
(phase 5). The calendar routes send `Cache-Control: public, s-maxage=43200` on 200s
(`calendar_response` in `api/routes/schedule.py`), so Vercel's CDN serves repeat polls
without invoking the function. A cached hit still counts as a Vercel CDN request, but
not as an invocation, active CPU or an R2 read.

### Why R2 and not Vercel Blob

Checked against Vercel's Blob pricing page (updated 2026-09-23). Hobby includes 1 GB
storage, 10,000 simple operations (a blob fetched by URL on a CDN miss, or `head()`),
2,000 advanced operations (`put()`, `copy()`, `list()`), and 10 GB Blob data transfer
a month. Over that, Blob is switched off for 30 days rather than billed, which for
the ICS cache is an outage of every calendar.

Advanced operations are the problem. Every refresh or cache-miss scrape writes two
blobs (ICS + sidecar), and every refresh pass lists the store:

| Per month | Blob Hobby | 100 calendars | 1,000 calendars | 10k calendars |
|---|---|---|---|---|
| Advanced ops (2 PUTs per scrape + lists) | 2,000 | ~900 | ~8,600 | ~86,000 |
| Simple ops (sidecar reads in refresh + CDN-miss ICS reads) | 10,000 | ~3-5k | ~30-50k | ~300k+ |

Blob fits today with about 2x headroom and runs out at roughly 200 calendars; R2's
free tier (1M writes, 10M reads) covers 10k calendars. Blob would also need a new
`BlobStore` implementation and loses the shared-bucket rollback to Hetzner. If an
all-Vercel setup ever matters more than headroom, it's one class in
`api/services/blob_store.py` picked by env var; Pro (usage-billed Blob) removes the cap.

What goes away: the Hetzner box, `docker-compose.yml`'s `worker`, `redis`, `caddy`,
`goaccess` and `uptime-kuma` services, `Caddyfile`, `goaccess.conf`, and the SSH deploy.
The `Dockerfile` stays, for local runs and as the escape hatch to Cloud Run.

What doesn't change: the scrapers, the registry, every public route and query key.
Calendar URLs already in people's calendars (`https://ukbinday.co.uk/api/v2/{lad}/subscribe/...`)
keep working, because the domain stays the same.

## Sizing (measured)

One real case per council module, 346 modules, run one at a time per process
(`/tmp/cpu_probe.py`, 2026-10-01, M-series Mac):

| | mean | p50 | p90 | p99 | max |
|---|---|---|---|---|---|
| CPU per scrape | 35 ms | 22 ms | 55 ms | 321 ms | 876 ms (Trafford, PDF) |
| Wall time per scrape | 1.8 s | 0.9 s | 3.9 s | 12.5 s | 22 s |

- Importing all 348 council modules takes 0.24 s of CPU. `ScraperRegistry.build()`
  took 0.54 s with the old `api/scrapers/` loaded and 0.15 s (after a 0.19 s import) on
  2026-10-01 with 370 IDs; without `api/scrapers/` it only gets smaller. Peak RSS was
  63-134 MB.
- Postcode lookup: `import duckdb` 0.12 s, first `read_parquet` query on the 16 MB
  `postcode_lookup.parquet` 31 ms, later queries 13 ms. Cold start cost is small (phase 3).
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

## Will it be free

Checked against Vercel's Hobby, fair-use and fluid-compute pricing pages and Cloudflare's
R2 pricing page on 2026-10-01.

**Today (~100 calendars): yes, with large margins.** Every allowance is under 5% used.

**Usage against the free allowances** (calendar size measured: a year of events is
~26 KB raw, ~4 KB gzipped; `GZipMiddleware` is on in `api/main.py`):

| Allowance (per month) | Free | 100 calendars | 10k calendars, uncached | Notes |
|---|---|---|---|---|
| Vercel invocations | 1M | ~10k | ~950k | Polls + page/API traffic + 30 cron runs |
| Vercel CDN requests | 1M | ~10k | ~950k + static | Counts every request, including static |
| Vercel active CPU | 4 h | < 0.1 h | ~2.5-3.5 h | Guessing ~10 ms CPU per poll (R2 GET + render) plus ~0.85 h refresh. Measure on the spike |
| Vercel provisioned memory | 360 GB-h | ~1 GB-h | ~40 GB-h | Billed while any request is in flight on an instance, I/O wait included |
| Vercel Fast Origin Transfer | 10 GB | ~0.04 GB | ~3.6 GB gzipped (~23 GB raw) | Missing from the earlier sizing. Gzip is what keeps it under |
| Vercel Fast Data Transfer | 100 GB | tiny | ~4 GB | |
| R2 Class A (writes, lists) | 1M | ~1k | ~100k | 2 PUTs per refresh or cache-miss scrape. Deletes are free |
| R2 Class B (reads) | 10M | ~10k | ~1.2M | One GET per poll + sidecar reads in the refresh |
| R2 storage | 10 GB | < 1 MB | ~300 MB | |

**What could cost money or break:**

1. **Hobby is non-commercial only.** Vercel's definition is broad: a deployment used "for
   the purpose of financial gain of anyone involved in any part of the production",
   explicitly including "a paid employee or consultant writing the code", ads, or
   selling anything. Donations are fine. This project qualifies: nobody is paid to work
   on it, and it has no ads or payments. Adding any of those would mean moving to Pro
   ($20/seat/month) or Cloud Run.
2. **Going over a Vercel limit doesn't bill, it pauses**, for up to 30 days. For a
   calendar feed that's an outage, so it matters more than a small bill would. Around
   5-10k calendars, invocations, CDN requests and active CPU all approach their caps
   together. The calendar cache (`s-maxage`, Vercel's CDN; Cloudflare's optionally) is
   the lever for invocations and CPU, but only if its TTL is longer than the gap
   between a calendar app's polls. With ~3 polls per calendar per day, a 6 h TTL saves
   little, so it's 12 h. Vercel CDN hits still count as CDN requests; only the
   Cloudflare proxy takes those off Vercel. Data only changes on
   the nightly refresh, so 12 h of staleness costs nothing. Watch Vercel's usage page
   monthly and move to Cloud Run before a cap, not after.
3. **R2 bills past the free tier rather than pausing.** Cloudflare asks for a payment
   method when you enable R2; confirm this when you enable it. Overage is $4.50 per
   million writes and $0.36 per million reads, so even 10x the 10k-calendar figures is
   pennies.
4. **Unchanged costs:** the domain. The address API (`ADDRESS_API_URL`) costs nothing: it
   is Mid Suffolk council's own address search on midsuffolk.gov.uk (a session-page GET for
   the CSRF token, then the search POST), used without an agreement. The risk is theirs to
   end, not a bill: if they rate-limit or block us, the address step fails for every
   council. Cloudflare's free plan covers DNS,
   proxy, cache and one rate-limiting rule. Uptime monitoring (UptimeRobot / Better Stack
   free tiers) is free.
5. **Not free:** Upstash is free only up to its own limits (not used by default), and
   Vercel log drains need Pro (Hobby keeps an hour of logs).

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
4. **Native wheels**: duckdb, curl_cffi, lxml, cryptography, pillow and pypdfium2 import
   and work on Vercel's Linux. All ship manylinux x86_64 wheels for Python 3.13, so the
   build needs no compiler. curl_cffi bundles its own libcurl-impersonate (23 MB); check a
   `Transport.CURL_CFFI` module actually completes a TLS handshake from Vercel, since 50
   modules depend on it.
5. **Region** `lhr1` is applied (check the response headers), and the cold start time.
6. `/api/v2/{lad}/view/{uprn}` returns dates for a handful of councils, including one
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
- The worker heartbeat (was `DATA_DIR/.worker_heartbeat`) is `meta/refresh_heartbeat.json`
  in the same store: `{"of": n, "shards": {"<i>": {"last_run", "entries", "stats"}}}`, one
  record per shard, reset when the shard count changes. `/api/v2/metrics` reads it instead
  of `app.state.refresh_job` (there is no long-lived job object on Vercel) and instead of
  counting the bucket. Its `ics_cache.last_refresh_age_seconds` is the oldest shard's age,
  for the stale-refresh monitor in phase 6.
- Concurrency: `IcsCache`'s per-UPRN `asyncio.Lock` protects only within one instance.
  Two Vercel instances writing the same UPRN at once would race the read-merge-write, and
  the last writer wins. The next refresh repairs it, since writes merge on stable UIDs. At
  this traffic that's acceptable. If it ever isn't, R2 supports conditional PUT
  (`If-Match` on the sidecar's ETag).
- Copy the existing cache: `scripts/vercel/hetzner_r2.sh` (rclone sync of the `bins_data` volume into the bucket).
  The store is recoverable anyway: every calendar URL carries `council`, `postcode` and
  `address`, so a lost object is rebuilt on its next poll (only past events are lost).
- Tests: `tests/test_scrape_cache.py` runs against the local store unchanged.
  `tests/test_blob_store.py` runs one contract against both stores, R2 through moto.
  moto can't intercept the `r2.cloudflarestorage.com` endpoint, so the test swaps in a
  mocked client: the real R2 endpoint and checksum settings (`when_required`, since R2
  rejects boto3's default CRC checksums) are first exercised by the spike.
- `docker-compose.yml` passes `R2_*` through to `api` and `worker`.

Ship it on Hetzner with `R2_*` env vars set. From here on, Hetzner and Vercel can both
serve from the same bucket, which is what makes cutover and rollback a DNS change.

### Phase 2: refresh as an HTTP endpoint

Vercel has no long-running process, so `RefreshJob.run_forever` and the `worker` service
become a cron-triggered route.

- `GET /api/v2/internal/refresh?shard=i&of=n`, rejected unless
  `Authorization: Bearer $CRON_SECRET` matches. Vercel sends that header on cron
  invocations when `CRON_SECRET` is set. Exclude it from the OpenAPI schema.
- `RefreshJob.run_once` gains `shard`, `of` and a `deadline`: take only UPRNs where
  `int(uprn) % of == shard`, stop queueing new work at ~250 s so the run finishes inside
  Vercel's 300 s limit, and leave the rest for the next day. Unfinished UPRNs stay
  eligible, so nothing is lost; they're just a day late.
- Shard count: at 10k calendars ~1,500 UPRNs are due on a given day; at 1.8 s wall each
  and `ICS_REFRESH_CONCURRENCY` raised to 8, that's ~340 s, so 4 shards with headroom.
  Today 1 shard is enough, so `vercel.json` has one cron
  (`/api/v2/internal/refresh?shard=0&of=1` at 05:00 UTC, two hours after Hetzner's worker). At scale, spread the shards across
  the night (Hobby fires anywhere within the hour):

  ```json
  {
    "framework": "fastapi",
    "regions": ["lhr1"],
    "functions": { "api/main.py": { "maxDuration": 300 } },
    "crons": [
      { "path": "/api/v2/internal/refresh?shard=0&of=4", "schedule": "0 1 * * *" },
      { "path": "/api/v2/internal/refresh?shard=1&of=4", "schedule": "0 2 * * *" },
      { "path": "/api/v2/internal/refresh?shard=2&of=4", "schedule": "0 3 * * *" },
      { "path": "/api/v2/internal/refresh?shard=3&of=4", "schedule": "0 4 * * *" }
    ]
  }
  ```

  The `functions` key is the entrypoint's file, `api/main.py` (Vercel FastAPI docs).
  Vercel's docs give no example of a query string in a cron `path`; the spike confirms the
  cron actually fires with it (`refresh_now.sh` covers the route itself).
- `run_once` stops scanning at the deadline and workers skip anything queued but not yet
  started; both count as `deferred` in the stats and heartbeat. Sidecars are read one at a
  time, about 50 ms each on R2, so a 2,500-UPRN shard spends ~2 min just reading. If
  shards run out of time, parallelise those reads before adding shards.
- While Hetzner still runs its worker (03:00 UTC) against the same bucket, both refresh.
  The cron runs two hours later, so `ICS_REFRESH_MIN_AGE_HOURS` (12) makes it skip what
  Hetzner just refreshed, and the two never scrape a UPRN at the same time (only Hetzner
  has the Redis scrape lock).
- Keep `python -m api.services.refresh_job` working (it calls `run_once` with one shard
  and no deadline) so Hetzner keeps refreshing until cutover.

### Phase 3: make the app serverless-friendly

Small changes, each independent:

- **Redis becomes optional in practice, not just in code.** Without `REDIS_URL`:
  - `scrape_lock.acquire` already returns `True`. Cross-instance coalescing is lost; see the
    concurrency note in phase 1.
  - `rate_limit` is already a no-op. The address step of `/find` (two requests to Mid
    Suffolk's site per lookup) stays behind Turnstile; the council answer is open. Add a Cloudflare rate-limiting rule on `/api/*` in
    phase 5 to replace the per-IP hourly limit.
  - The `api:request_counts` analytics hash and `/status`'s `redis_connected` fall away.
    Cloudflare and Vercel analytics replace GoAccess.
  - If any of these turn out to matter, Upstash Redis has a free tier and the existing code
    works with it unchanged via `REDIS_URL=rediss://...` (redis-py over TLS). The cost is a
    TLS connect on every cold start plus one round trip per rate-limit check and two per
    scrape lock. Turn it on first for the scrape lock if duplicate scrapes of one UPRN
    show up in logs, since that's the only Redis use with a correctness effect.
  - The `ratelimit:*` flush stays in the Hetzner deploy job and goes with it in phase 6.
- **Scraper health** (`registry.record_success/failure`, shown on `/councils` and
  `/metrics`) is in-memory per instance, so on Vercel it resets on every cold start. That's
  harmless, but don't treat it as meaningful there. The live test and the `working` flags
  are the real source of truth.
- **Postcode lookup.** `CouncilLookup` uses plain duckdb (there is no ibis, whatever older
  notes say) and runs `read_parquet` on every request against the bundled
  `api/data/postcode_lookup.parquet` (16 MB, 1.6M rows). The bundle is read-only, which
  duckdb's in-memory connection doesn't mind. Leave it as is. If cold starts matter later,
  load the parquet once into an in-memory table in the lifespan, or drop duckdb (57 MB of
  the bundle) for a sorted postcode->LAD file and a binary search.
- **Timeouts.** A scrape is bounded three ways: `Http` per-request `DEFAULT_TIMEOUT` (20 s),
  `SCRAPER_TIMEOUT` (30 s) around the whole `run()`, and on Vercel the function's
  `maxDuration`. The whole app is one function, so `maxDuration` is 300 s for every route
  (the refresh needs it); user routes are held well under that by `SCRAPER_TIMEOUT`. A
  cache-miss `/{lad}/view` is at most the 30 s scrape plus address and postcode work, inside
  Cloudflare's 100 s proxy timeout. The slowest measured scrape was 22 s, so
  `SCRAPER_TIMEOUT` stays at 30. Wall time spent waiting on councils isn't active CPU, so
  it doesn't eat the 4 h budget, but it does count toward provisioned GB-hours.
  `SCRAPE_LOCK_MAX_WAIT_S` only matters with Redis.
- **Static files**: Vercel promotes `app.mount("/static", StaticFiles(...))` to its CDN at
  build time, but keeps them in the function when there's top-level middleware, which
  `api/main.py` has (`log_requests`). Set `[tool.vercel.fastapi.static] cdn = true` to
  promote anyway; static responses then skip the security headers `log_requests` adds,
  which can be set in `vercel.json` `headers` instead. `api/static/` is 1.2 MB, almost all
  `coverage.geojson`. The three Jinja templates (`index.html`, `coverage.html`,
  `api-docs.html`) are rendered by the function and need no change.
- **Logs**: JSON to stdout already. Hobby keeps runtime logs for 1 hour, so anything
  you'd want to look back on (refresh stats) goes in the heartbeat object.

### Phase 4: deploy pipeline and council probe

- **Dependencies.** Test and tooling packages are in the `dev` group. Measured
  2026-10-01: the production dependencies plus `boto3`, installed for
  `x86_64-manylinux_2_28` / Python 3.13, come to **197 MB** (that count still included
  `requests`, now gone). The biggest are duckdb (57 MB), botocore (25 MB), curl_cffi
  (23 MB), pillow (20 MB, pulled in by pdfplumber), lxml and cryptography (13 MB each).
  That's well inside the 500 MB limit. If size ever matters, replacing boto3 with signed
  httpx calls to R2 saves 25 MB.
- **Bundle exclusions.** Exclude `pipeline/`, `tests/`, `scripts/`, `node_modules/` and
  `**/__pycache__`. The committed ONS parquets in `pipeline/data/` (104 MB) are for test
  generation, not runtime. Only `api/data/postcode_lookup.parquet` (16 MB) and
  `api/data/lad_lookup.json` are read at runtime, plus `api/councils/_aliases.json`.
- **CI.** `.github/workflows/deploy.yml` runs `smoke-test`, then two deploy jobs: the
  Hetzner `appleboy/ssh-action` job (git reset, rewrite `.env` with the Turnstile secrets,
  `docker compose up -d --build`, flush rate-limit keys), unchanged, and `deploy-vercel`
  (`vercel deploy --prod`, built remotely: the upload honours `.vercelignore`, a local
  `vercel build` didn't). The Vercel
  job skips itself until the `VERCEL_TOKEN`, `VERCEL_ORG_ID` and `VERCEL_PROJECT_ID`
  secrets exist. Both deploy on every push until phase 6, so either can serve the domain.
  `vercel.json` turns off Vercel's own Git deploys, so a failing smoke test still blocks
  production. `scripts/deploy/deployment.py` (Hetzner provisioning, using `hcloud` and
  `paramiko`) goes in phase 6.
- **Env vars** in Vercel (production): `ADDRESS_API_URL`, `ADDRESS_API_COMPANY_ID`,
  `TURNSTILE_SITE_KEY`, `TURNSTILE_SECRET`, `BASE_URL`, `CORS_ORIGINS`, `R2_ACCOUNT_ID`,
  `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET`, `CRON_SECRET`, `ENV=production`,
  `LOG_FORMAT=json`, `SCRAPER_TIMEOUT=30`, `ICS_REFRESH_CONCURRENCY=8`. Not
  `RUN_REFRESH_JOB` (set it to `0`; the background task can't run there) and not `REDIS_URL`.
- **Council probe.** Requests now leave from AWS London instead of Hetzner, and a council
  that blocks AWS ranges would break silently. Before cutover, run
  `uv run python -m scripts.vercel_probe --base-url https://<preview>.vercel.app`
  (leave `TURNSTILE_SECRET` unset on the preview). It runs the sampled cases from
  `tests/lad_test_cases.json` against the preview's `/api/v2/{lad}/view/{uprn}`, classifies
  them the way the live test does, and diffs per-LAD status against
  `tests/output/lad_integration_output.json`; it exits 1 on any regression. Councils that pass locally but fail
  from Vercel are the list to deal with. Small numbers can be left on a `NeedsBrowser`
  deeplink; a large number means going to Cloud Run (europe-west2) instead, with the same image.

### Phase 5: cutover

1. `scripts/vercel/cutover.sh` adds the domain to the Vercel project and points the
   Cloudflare records at Vercel, unproxied (Vercel issues the certificate). Calendar
   caching is already on via the app's `s-maxage` header.
2. Optional, later (around 5k calendars, or if abuse shows up): DNS is already on
   Cloudflare, so turn on the proxy with SSL "Full (strict)" and add these rules. The
   cache rule moves calendar hits off Vercel's 1M CDN-request allowance; the
   rate-limit rule replaces `RATE_LIMIT_HOURLY`, which is a no-op without Redis
   (Turnstile still guards the address step of `/find`).
   - Cache rule: `/api/v2/*/subscribe/*` and `/api/v2/*/download/*`, eligible for cache, edge TTL 12 h (longer than the gap between a calendar app's polls; see "Will it be free"), cache key includes
     the query string (the default). Expression: `(http.request.uri.path wildcard "/api/v2/*/subscribe/*") or (http.request.uri.path wildcard "/api/v2/*/download/*")`; if the
     dashboard rejects `wildcard` on Free, `starts_with(http.request.uri.path, "/api/v2/") and (http.request.uri.path contains "/subscribe/" or http.request.uri.path contains "/download/")`
     (`matches` regex needs Business). Free allows 10 cache rules and a 2 h minimum edge TTL. Add a status-code TTL of no-cache for 500-599: the docs don't say whether the
     TTL override caches 5xx. The API also sends `Cache-Control: no-store` on every 5xx.
   - Cache rule: `/static/*`, edge TTL 1 day.
   - Rate-limiting rule on `/api/*`, per IP, to replace `RATE_LIMIT_HOURLY`.
3. Watch for a few days: Vercel usage (invocations, active CPU), the refresh heartbeat,
   and a calendar subscription that actually updates.
4. Rollback is `cutover.sh --rollback .vercel/dns_backup_<stamp>.json`. Both serve from
   the same R2 bucket, so no data moves either way. Keep the box for two weeks.

### Phase 6: decommission

- Delete the Hetzner server, the `deploy` (SSH) job in `deploy.yml`, and the
  `SERVER_HOST` / `SSH_PRIVATE_KEY` secrets.
- Remove `Caddyfile`, `goaccess.conf`, and the `redis`, `caddy`, `goaccess`, `uptime-kuma`
  and `worker` services from `docker-compose.yml` (keep `api` for local use).
  `tests/test_deploy.py` and `tests/test_deploy_docker.sh` shrink to match.
- Monitoring: replace Uptime Kuma with a free external monitor (UptimeRobot, Better Stack)
  on `/api/v2/status`, plus a second check that fails when the refresh heartbeat in R2 is
  older than 36 h (expose its age on `/api/v2/metrics` or `/status`). Replace GoAccess with
  Cloudflare Web Analytics and the Cloudflare/Vercel request dashboards. Hobby keeps
  runtime logs for an hour, so errors worth keeping need a log drain or Sentry's free tier.
- Delete `scripts/deploy/deployment.py` and drop `hcloud` and `paramiko` from the dev group.
- Update `AGENTS.md` (Infrastructure, CI/CD, `ics_cache`, `refresh_job`, `scrape_lock`,
  `deploy/deployment.py` becomes `scripts/deploy/deployment.py`, then goes; drop the ibis mentions).

## Risks, biggest first

| Risk | Phase it surfaces | Mitigation |
|---|---|---|
| Councils block or throttle AWS (Vercel) egress IPs that Hetzner's weren't | 4 (council probe) | Diff a preview run against the last live run; few failures go to `NeedsBrowser`, many mean Cloud Run europe-west2 |
| R2 read-merge-write races across instances lose a write | 1 | Stable UIDs mean the next refresh repairs it; conditional PUT on the sidecar ETag if it ever matters |
| Refresh pass outgrows 300 s | 2 | Shards plus a deadline; unfinished UPRNs stay eligible for the next night |
| Calendar polls exhaust the 1M invocation cap (feature pauses, no bill) | 5 | `s-maxage` 12 h keeps polls on Vercel's CDN; Cloudflare proxy before ~10k calendars takes them off the CDN-request cap too |
| curl_cffi impersonation behaves differently on Vercel's Linux | 0 | Spike item 4; the 50 `CURL_CFFI` modules are in the council probe |
| Losing Redis drops cross-instance scrape coalescing and per-IP limits | 3 | Turnstile on `/find`, Cloudflare rate-limit rule, Upstash if needed |

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
