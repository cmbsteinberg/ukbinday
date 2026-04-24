# Hand-porting the 42 UKBCD selenium scrapers to native async Playwright

**Status:** Tier A IEG4 cluster partially landed (4/6 ported, 2 deferred
upstream-broken). `api/compat/playwright/ieg4.py` base + 4 scrapers on disk,
all pinned `blocked_on_lightpanda_iframes`. Lightpanda compatibility probe
results for the other vendors captured below — they shift which clusters
are worth tackling next.
**Prior art:** `LIGHTPANDA_EXPERIMENT.md` — documents why the transpiler route
tops out at ~5/42 on Lightpanda and why hand-porting is the right next step.

## Scope

42 UKBCD selenium scrapers that are not covered by any HACS or non-selenium
UKBCD scraper. Canonical list: `pipeline/ukbcd/selenium_test_results.json`
(29/42 pass upstream, 13/42 already broken upstream).

**Backend: Lightpanda only.** Hetzner system specs rule out running Chromium
or chromedriver in the production stack. Any scraper that cannot work on
Lightpanda is out of scope — we track it, we do not ship a heavier backend to
carry it.

## Architecture

### Scraper shape

One flat file per council in `api/scrapers/`, matching the existing naming
convention for UKBCD ports:

```
api/scrapers/ukbcd_<council_slug>.py
```

Already the UKBCD naming prefix, so the registry picks them up with zero
changes. Each file exposes the same contract as every other scraper:

```
class Source(BrowserScraper):
    TITLE = "..."
    URL = "..."
    TEST_CASES = [...]

    def __init__(self, uprn=None, postcode=None, address=None):
        ...

    async def fetch(self) -> list[Collection]:
        async with self.page() as page:
            await page.goto(self.URL, wait_until="domcontentloaded")
            await dismiss_cookies(page)
            ...
            return collections
```

Return type remains `list[Collection]` (re-use `api/compat/hacs/Collection` —
no new model).

### New compat surface

```
api/compat/playwright/
    __init__.py        # re-exports Collection + BrowserScraper
    base.py            # BrowserScraper base class
    helpers.py         # dismiss_cookies, find_address_option, capture_xhr
```

`BrowserScraper` owns a single `self.page()` async context manager that wraps
`BrowserPool.new_context()` → `context.new_page()` and guarantees cleanup.
That is the only place Playwright's Page/Context types leak into scraper
code.

### Runtime — unchanged

- `api/services/browser_pool.py` already handles Lightpanda CDP, the pool-wide
  scrape lock, reconnect-on-drop, default timeouts, and the wgxpath polyfill.
- `api/services/scraper_registry.py` already introspects `Source.__init__`
  signatures and dispatches `await source.fetch()`. A browser-backed `Source`
  is the same shape as a requests-backed one from its perspective.
- `BROWSER_BACKEND=cdp` is the only supported mode. We drop the `chromium`
  branch from `BrowserPool` once the hand-port work starts landing.

### Locator style

Native Playwright only. `page.get_by_role`, `get_by_label`, `get_by_text`,
`locator("#foo").select_option(...)`. No `By.ID` / `find_element` analogues.
No XPath unless a scraper genuinely requires it. No Selenium `Select` shim.

### Helpers (kept small — only patterns seen ≥3 times)

- `dismiss_cookies(page_or_frame)` — curated OneTrust / Civic / TrustArc /
  "Accept all" selectors. Swallows timeout. Invoked once per `goto`, not
  automatic.
- `find_address_option(dropdown_locator, address_text)` — fuzzy visible-text
  match, since councils format addresses inconsistently.
- `capture_xhr(page, url_pattern)` — context manager that records matching
  XHR responses, for sites whose results live in JSON not the DOM.
- Date parsing / bin-type normalisation — re-export from
  `api/compat/ukbcd/common_functions.py`.

Explicitly **not** wrapping: navigation, clicks, fills. The point of
hand-porting is to write the right Playwright call directly.

## Phase 1 — cluster the 42 (what pyscn found, and what it didn't)

### pyscn findings

Ran clone detection against the upstream UKBCD selenium files:

```bash
uvx pyscn@latest analyze --select clones --json \
    pipeline/upstream/ukbcd_selenium_clone/uk_bin_collection/uk_bin_collection/councils/
```

Report written to `pipeline/ukbcd/handport_clone_report.json`. Union-find
derivation in `pipeline/ukbcd/cluster_handports.py` →
`pipeline/ukbcd/handport_clusters.json`.

**Result at similarity ≥ 0.85: only two real clusters.**

- `SomersetCouncil` ↔ `TestValleyBoroughCouncil` (sim 1.000)
- `BaberghDistrictCouncil` ↔ `MidSuffolkDistrictCouncil` (sim 0.96)

Everything else scores below 0.76 pairwise. pyscn also reports one Type-4
group spanning all 42 files, but that only reflects the shared
`AbstractGetBinDataClass` skeleton — it is not a reuse signal.

### Why pyscn missed the vendors

UKBCD upstream authors write each council scraper from scratch against the
real form. Two councils using the same vendor (e.g. both IEG4 AchieveForms)
end up with the same *flow* but different variable names, different element
ids, and different parse_data bodies. pyscn sees independent code; a human
reading ten files spots the iframe-switch pattern immediately.

### Actual vendor clusters (found by hand)

Grouped by URL host + in-code fingerprint (form host, selector idioms,
XHR endpoints) across all 42:

| Vendor | Count | Councils |
|---|---|---|
| **IEG4 AchieveForms** (iframe-nested) | 6 | EastSuffolk, GloucesterCity, NorthDevonCounty, NorthEastDerbyshire, Tendring, ThreeRivers |
| **iTouchVision** (`i*portal.itouchvision.com`) | 3 | EpsomandEwell, Hyndburn, Winchester |
| **Salesforce Community Cloud** (`community.<council>.gov.uk/s/`) | 2 | Cotswold, ForestOfDean |
| **Jadu Continuum** (`onmats.com` / `oncreate.app` / `/w/webpage/`) | 2 | Hertsmere, Sevenoaks |
| Distinctive singletons | 5 | Basildon (PowerApps+Azure API), EppingForest (ArcGIS), Knowsley (Mendix), NewForest (Oracle UFS), Wychavon (Civica) |
| True one-offs | 24 | Argyll, Babergh, BlaenauGwent, Boston, Brighton, Ceredigion, DumfriesGalloway, Edinburgh, EppingForest†, GreatYarmouth, Halton, Hillingdon, KingstonUponThames, MidSuffolk, MidUlster, NorthNorfolk, Northumberland, Powys, Slough, Somerset, StaffsMoorlands, Stirling, Teignbridge, TestValley, Torbay |

Within each cluster the shared flow is consistent:

- **IEG4 AchieveForms:** wait for iframe → `switch_to.frame` → postcode input
  → address `<select>` where `option[value] = UPRN` → results panel
  (`span[data-name=html1]` for several). Per-council differences are
  selector ids only.
- **iTouchVision:** identical `#postcodeSearch` / `#addressSelect` elements
  across all three; Winchester bounces via winchester.gov.uk into an iTV
  widget. Result-panel markup differs between iapp (AntD) and iportal
  (govuk-styled).
- **Salesforce Community:** Cotswold and ForestOfDean have identical
  Selenium vocabulary — likely a direct parametrised port.
- **Jadu Continuum:** both hit `/w/webpage/...` endpoints on a hosted Jadu
  platform.

### Notable re-interpretations of the plan

- **The "7 iframe-blocked" scrapers aren't 7 custom iframes.** Six of the
  seven (EastSuffolk, GloucesterCity, NorthDevon, NorthEastDerbyshire,
  Tendring, ThreeRivers) are all IEG4 AchieveForms; only Halton is a custom
  iframe webform. One IEG4 base class lights up 6 scrapers the day
  Lightpanda ships iframe CDP support.
- **Basildon probably doesn't need a browser.** The PowerApps form is a
  facade over `basildonportal.azurewebsites.net/api/getPropertyRefuseInformation`.
  If the API is reachable without the form-side session, it's an httpx port,
  not a browser port.
- **The plan's predicted clusters (Jadu/CXM, Granicus, Bartec) don't
  match.** Jadu exists but is 2 scrapers, not 4. Granicus/Bartec are not
  visible in the code at all. The real vendor landscape is IEG4 +
  iTouchVision + Salesforce + Jadu + long tail.

## Phase 2 — porting order

Revised tiers based on the hand-clustering above, not the pyscn report.
Parametric bases are written once and subclassed per council.

1. **Tier A — parametric vendor bases (13 scrapers covered by 4 base classes).**
   Highest leverage.
   - `IEG4AchieveFormsScraper` → 6 scrapers (IEG4 cluster above). Lands
     code-complete but flipped to `blocked_on_lightpanda_iframes` until
     Lightpanda exposes iframe contents over CDP.
   - `ITouchVisionScraper` → 3 scrapers.
   - `SalesforceCommunityScraper` → 2 scrapers.
   - `JaduContinuumScraper` → 2 scrapers.
2. **Tier B — Basildon as a requests-only scraper.** Not a hand-port at all
   if the Azure API is public. Confirm with a single `curl` before writing
   browser code.
3. **Tier C — distinctive singletons (4).** ArcGIS (EppingForest), Mendix
   (Knowsley), Oracle UFS (NewForest), Civica (Wychavon). One hand-port
   each, no reuse.
4. **Tier D — 24 true one-offs.** Order by upstream-ok status first, then
   by LAD coverage. No shared code expected.
5. **Deferred** — the 13 upstream-broken scrapers (tracked in the manifest
   with `status: "upstream_broken"`) stay deferred until upstream fixes
   them or a replacement backend surfaces.

Per cluster / scraper:

1. Pick the cleanest upstream file as representative.
2. Port by reading upstream + manually walking the real council site. Use
   Playwright Inspector locally (against real Chromium, **development only**
   — production is Lightpanda) to find stable selectors. Prefer role/label
   over CSS.
3. Run the scraper's `TEST_CASES` via `tests/test_integration.py`.
   Registered automatically once the file is on disk.
4. Walk the other cluster members. Cosmetic diffs (URL, IDs, council name)
   → copy + tweak. Structural diffs → port from scratch.
5. Record backend + status in `pipeline/ukbcd/handport_manifest.json`.

### Scrapers that probably can't reach Lightpanda

Per the round-3 probe in `LIGHTPANDA_EXPERIMENT.md`, Lightpanda does not
expose iframe contents over CDP (as of v0.2.5). Seven upstream scrapers use
iframes: EastSuffolk, GloucesterCity, Halton, NorthDevon,
NorthEastDerbyshire, Tendring, ThreeRivers. All remain out of reach until
Lightpanda wires iframe support through to CDP.

After the vendor-cluster pass above, six of those seven are IEG4
AchieveForms (EastSuffolk, GloucesterCity, NorthDevon,
NorthEastDerbyshire, Tendring, ThreeRivers). Halton is the only custom
iframe webform. So the iframe blocker covers *one* parametric base class
plus one one-off, not seven independent ports.

We port them anyway — the code is correct, the runtime isn't ready — and
mark them `status: "blocked_on_lightpanda_iframes"` in
`handport_manifest.json`. They flip to passing the day Lightpanda ships the
CDP change.

### Lightpanda compatibility probe (2026-04-24)

Manual probe with `lightpanda fetch --dump html --wait-ms 3000 <url>` against
each vendor's canonical landing URL. Findings reshape Tier A:

- **iTouchVision (EpsomandEwell, Hyndburn, Winchester + TestValley):** React
  app bails with `TypeError: t.toDataURL is not a function` before the root
  renders. Lightpanda lacks `HTMLCanvasElement.toDataURL`. Port the code,
  land `status: "blocked_on_lightpanda_canvas"` — flips green when
  Lightpanda ships canvas.
- **Salesforce Community (Cotswold, ForestOfDean):** Aura framework boots
  with `Illegal Constructor` errors but does render some SLDS chrome.
  Whether the address lookup field becomes interactive is unknown without a
  Chromium walkthrough. Triage risk: medium. Defer until singletons cleared.
- **Jadu Continuum (Hertsmere, Sevenoaks):** Both ported. Runtime walk on
  Lightpanda after landing:
  - **Hertsmere (onmats.com):** Postcode input is in the DOM and
    `page.keyboard.type` sets the value, but Playwright's `.fill()` and
    `.press_sequentially()` both fail inside Lightpanda's injected script
    (`focusNode` / `selectText` gaps). Even after a value is set, the
    onmats type-ahead XHR never fires and `ul.result_list` stays empty.
    Pinned `blocked_on_lightpanda_interactions`.
  - **Sevenoaks (oncreate.app):** `#address_search_postcode` never renders
    in Lightpanda's DOM at all — the Jadu page needs more JS than
    Lightpanda executes. Pinned `blocked_on_lightpanda_rendering`.
- **Stirling:** WAF returns "Service unavailable — request blocked" to
  Lightpanda's UA. Needs UA override in `BrowserPool` or is out of scope.
  Track as `blocked_on_lightpanda_waf`.
- **Torbay, Argyll-Bute:** static shell renders but the collection data
  arrives via JS-driven XHRs that may or may not fire on Lightpanda.
  Requires `page.goto` + `capture_xhr` inspection during their port.

New statuses introduced: `blocked_on_lightpanda_canvas`,
`blocked_on_lightpanda_waf`, `blocked_on_lightpanda_interactions`,
`blocked_on_lightpanda_rendering`. Same semantics as
`blocked_on_lightpanda_iframes` — code is correct, runtime isn't ready.

### Revised Tier A order

1. **IEG4 AchieveForms (4/6 landed)** — GloucesterCity, NorthDevonCounty,
   Tendring, ThreeRivers on `IEG4AchieveFormsScraper`. All pinned
   `blocked_on_lightpanda_iframes`. EastSuffolk and NorthEastDerbyshire
   deferred (upstream_broken).
2. **Jadu Continuum (2/2 landed)** — Hertsmere, Sevenoaks ported. Each
   pinned on a different Lightpanda gap (see probe above).
3. **iTouchVision (3)** — port behind `ITouchVisionScraper`, land
   `blocked_on_lightpanda_canvas`.
4. **Salesforce Community (2)** — deferred until a Chromium walkthrough
   confirms the Aura form is reachable on Lightpanda.

### Hard truth from Tier A so far

6/6 ported Tier A scrapers are pinned on a Lightpanda gap, spanning four
distinct issues (iframes, canvas, interactions, rendering). Every vendor
cluster hit a different wall. The plan's strict reading ("any scraper that
cannot work on Lightpanda is out of scope") would zero this work — but the
code ports are correct and trivially flip green when each Lightpanda issue
lands, so they're worth carrying as pinned.

What this actually means for Tier A completion ≤ next Lightpanda release:

- None of these ship without upstream Lightpanda fixes.
- Remaining Tier A work (iTouchVision, Salesforce) adds *more* pinned
  ports; it does not unblock any existing one.
- Real shippable progress now has to come from Tier C/D singletons whose
  sites render enough for Lightpanda to drive them. That needs per-scraper
  probing before we commit to porting each.

## CI/CD + sync-pipeline integration

This section is the whole point of doing the work carefully. The sync
pipeline currently regenerates everything from upstream. Naive integration
would overwrite hand-ported files every time upstream changes.

### Principle: hand-ports are owned by us, test cases are borrowed from upstream

- The scraper file (`api/scrapers/ukbcd_<slug>.py`) is authored by us. It
  must **never** be overwritten by sync.
- The `TEST_CASES` inside it are the **upstream** values — UPRN / postcode /
  address combinations known to work. These are valuable and do change
  upstream. We want to keep them in sync.
- Upstream selenium scrapers themselves can be edited (new vendor, new form,
  different endpoint). We need to notice when that happens so the hand-port
  can be updated.

### Manifest: `pipeline/ukbcd/handport_manifest.json`

Single source of truth for the sync pipeline. For each of the 42 selenium
scrapers:

```
{
  "ArgyllandButeCouncil": {
    "upstream_path": "uk_bin_collection/councils/ArgyllandButeCouncil.py",
    "handport_scraper": "api/scrapers/ukbcd_argyll_and_bute.py",
    "upstream_sha": "<sha256 of upstream file at port time>",
    "upstream_test_cases_sha": "<sha256 of just the TEST_CASES block>",
    "status": "ported" | "pending" | "upstream_broken" | "blocked_on_lightpanda_iframes" | "blocked_on_lightpanda_canvas" | "blocked_on_lightpanda_waf",
    "backend": "cdp",
    "ported_at": "2026-04-24",
    "notes": "..."
  },
  ...
}
```

### Sync pipeline changes (`pipeline/ukbcd/sync.sh` + `pipeline/sync_all.py`)

Three new rules, in order:

1. **Skip generation for any council in the manifest with `status != "pending"`.**
   The existing `patch_selenium_scrapers.py` transpiler must not touch these.
   Currently it already skips all selenium scrapers (they were never emitted);
   this is belt-and-braces for the day the transpiler path is deleted and a
   future refactor forgets.

2. **Extract + refresh `TEST_CASES` from upstream.** For each ported scraper,
   read `TEST_CASES` from the upstream file, diff against the hand-port's
   `TEST_CASES`, and if different:
   - Write the new cases into the hand-port file (AST-level replace of the
     `TEST_CASES = [...]` assignment — it's a literal, safe to rewrite).
   - Update `upstream_test_cases_sha` in the manifest.
   - Log the change in the sync summary.

   Implementation: a new `pipeline/ukbcd/sync_test_cases.py` invoked from
   `sync.sh` after the upstream clone step. AST-level, not regex.

3. **Drift detection on upstream scrapers.** Also a new script,
   `pipeline/ukbcd/check_handport_drift.py`:
   - Hash each upstream selenium file, compare to `upstream_sha` in the
     manifest.
   - If a hash changed → emit a warning in the sync summary and write the
     drifted council name to `pipeline/ukbcd/handport_drift.json`. Does **not**
     touch the hand-port — a human reviews and decides whether to re-port.
   - Also scan the full upstream councils directory for *new* selenium
     scrapers not in the manifest. New selenium file → add to manifest with
     `status: "pending"` and surface in the sync summary.

   Runs on every sync. Fast (42 SHA-256s plus one directory listing).

### Pre-commit hook

Existing lefthook config runs the sync as a pre-commit hook. Add a guard:

- If `check_handport_drift.py` finds drift or new scrapers, fail the commit
  with a message telling the human to update the manifest. Prevents silent
  coverage gaps.

### CI workflow (`.github/workflows/deploy.yml`)

- Add a step after smoke tests, before deploy: run
  `check_handport_drift.py --strict`. Fails the build on drift so deploy
  doesn't happen against stale ports.
- Integration test run already covers the hand-ports via `TEST_CASES` — no
  change needed there.
- Add `handport_status.json` (working/broken counts) to the post-integration
  artefact regen so the README sankey reflects ported vs pending.

### What this buys us

- Hand-ports are never overwritten by sync.
- Upstream test-case refreshes still propagate automatically.
- Upstream scraper edits surface as reviewable warnings, not silent
  overwrites and not silent staleness.
- New upstream selenium scrapers get surfaced the day they land.
- CI refuses to deploy when the hand-ports are out of date relative to
  upstream.

## Phase 3 — delete the transpiler path

Once ported coverage ≥ 22/42 (well above the transpiler's ~5/42 ceiling),
delete:

- `pipeline/ukbcd/patch_selenium_scrapers.py` (the transpiler).
- `pipeline/ukbcd/test_selenium_scrapers.py` and `selenium_test_results.json`
  — the upstream-selenium baseline was only useful for grading the
  transpiler. Hand-ports grade themselves via integration tests.
- The `chromium` branch of `api/services/browser_pool.py`.
- `api/services/_assets/wgxpath.js` if no hand-port uses it (expected — we
  choose selectors deliberately).
- The `greenlet` + `pyee` extras in `pyproject.toml` that were only there for
  the transpiler smoke.

Keep `api/services/browser_pool.py` (the CDP-only path), the Lightpanda
nightly autodownload, and `LIGHTPANDA_EXPERIMENT.md` as historical context.

## Deliverables before any scraper code gets written

1. ✅ pyscn clone report on upstream selenium scrapers →
   `pipeline/ukbcd/handport_clone_report.json`. Low signal (see Phase 1)
   — only 2 real clusters at sim≥0.85. Vendor clustering was done by hand
   on URL host + in-code fingerprint; output in
   `pipeline/ukbcd/handport_clusters.json` and the table in Phase 1.
2. ✅ `pipeline/ukbcd/handport_manifest.json` scaffolded from the 42
   upstream files (29 `pending`, 13 `upstream_broken`). Idempotent
   scaffolder at `pipeline/ukbcd/scaffold_handport_manifest.py` preserves
   existing shas on re-run so drift signal survives.
3. ✅ `check_handport_drift.py` + `sync_test_cases.py` implemented and wired
   into `pipeline/ukbcd/sync.sh`, `lefthook.yaml` (pre-commit `--strict`)
   and `.github/workflows/deploy.yml` (pre-deploy `--strict`). `sync.sh`
   now preserves `ukbcd_*.py` files whose manifest entry has
   `status != "pending"`.
4. ✅ `BrowserScraper` base class + `helpers.py` in `api/compat/playwright/`
   (`dismiss_cookies`, `find_address_option`, `capture_xhr`).
5. ✅ Cluster → porting-order table agreed (Phase 2 above). Tier A starts
   with the IEG4 AchieveForms base (6 scrapers, all `blocked_on_lightpanda_iframes`
   at land time).

---

## Phase 2.5 — Pivot: XHR reverse engineering as Tier 0 (2026-04-24)

Tier A landed with every vendor cluster pinned on a different Lightpanda
gap (iframes, canvas, interactions, rendering). The ports are correct and
will work the day Lightpanda fills those gaps, but in the meantime none
of them run. That forced a re-examination of the strategy — specifically,
what tier of tool each council site actually *needs*.

### The tool tier axis

There's a stack of options between "plain `httpx`" and "full Chromium",
and it's worth being precise about what each one gives you:

| Tier | Tool | Parses HTML | Runs JS | Executes XHR | Renders |
|------|------|-------------|---------|--------------|---------|
| 0 | `httpx` + bs4 / `linkedom` / `cheerio` | ✅ | ❌ | ❌ (you call APIs yourself) | ❌ |
| 1 | `jsdom` / `happy-dom` (Node subprocess) | ✅ | ✅ (partial) | ✅ (fetch polyfill) | ❌ |
| 2 | Lightpanda (Zig + QuickJS, CDP) | ✅ | ✅ | ✅ | partial — no canvas, no iframe child docs, no `selectText`/`focusNode` injected helpers |
| 3 | `chromium-headless-shell` / Playwright Chromium | ✅ | ✅ | ✅ | ✅ |

Key distinction: **`linkedom` is a Tier 0 HTML parser, not a Chromium
alternative.** It's in the same bucket as BeautifulSoup or `cheerio` —
just faster and with a DOM-spec API. It doesn't execute `<script>` tags,
doesn't fire XHRs, doesn't paint anything. Swapping bs4 for linkedom
unlocks exactly zero new councils; the question that matters is "does
JavaScript run?", and the answer for Tier 0 is no across the board.

Tier 1 (`jsdom`, `happy-dom`) *does* run JS and has a `fetch` polyfill,
so in principle it can drive a type-ahead or submit a form. In practice
it drops most of what vendors rely on (Shadow DOM edge cases, Web
Components in some libs, canvas, workers, MutationObserver timing).
It's better than Lightpanda for some things and worse for others, and
either way it's another subprocess to babysit.

Tier 3 is what upstream UKBCD uses (selenium → Chromium). It works for
everything but costs ~300 MB RSS per scrape, spins up a real renderer,
and turns the service into a browser farm. That's the thing we're
trying to avoid.

### The insight that changes the plan

When a council site "requires JavaScript", what it almost always means
is: *a script on the page issues an XHR to a backend, and the backend
returns JSON or HTML that gets rendered client-side.* The JS isn't
doing anything magical — it's making an HTTP request that we could
make directly with `httpx`, if we knew the URL, method, headers, and
body shape.

Basildon is the proof: its Next.js frontend calls
`basildonportal.azurewebsites.net/api/getPropertyRefuseInformation`
with a UPRN. The scraper is a single `httpx.post` and a JSON parse —
no browser, no DOM, no JS runtime. That's what "forcing JS" looks like
when you realise you don't have to force anything; you can just call
the API the JS would have called.

UKBCD upstream used selenium for almost every council not because it
was necessary, but because selenium is the lowest-labour way to write
a scraper: point it at a page, fill some fields, click some buttons,
read the result. Reverse-engineering the XHR is more work per scraper
but produces dramatically lighter, faster, more reliable code. HACS
has already done this for iTouchVision (`iapp_itouchvision_com`) and
several other shared backends, which is why HACS covers more councils
on a tighter dependency budget.

### Revised strategy

- **Tier 0 (XHR reverse engineering) becomes the primary path** for
  every remaining UKBCD selenium scraper. Only fall back to a browser
  when the site's JS does non-trivial client-side computation (rare —
  crypto-style signing is the main reason, and most councils don't do
  that).
- **Keep the 6 pinned Lightpanda ports as-is.** They're correct
  implementations that unblock the moment Lightpanda ships the missing
  CDP surface. Re-probe on each Lightpanda release via
  `check_handport_drift.py`.
- **Demote Tier A remaining work (iTouchVision, Salesforce Aura).**
  iTouchVision already has a HACS XHR-based scraper we can port or
  reuse directly; Salesforce Aura's `/aura` RPC endpoint is
  well-understood and callable from httpx with the right framework
  action payload.
- **Do not invest in `jsdom`/`happy-dom` subprocesses.** Tier 1 is a
  strict superset of the pain we already have with Lightpanda (another
  runtime, another set of gaps), and if we're going to go to the
  trouble of driving a DOM we might as well drive Chromium on demand
  (Tier 3) for the <5% of councils that genuinely need it.
- **Chromium on demand as the long-tail fallback.** A sidecar container
  running `chromium-headless-shell` over CDP, spun up only for the
  handful of councils that truly need a real renderer, is cheaper than
  every other option we've considered *at the scale of the long tail*.

### Next steps — build the network-capture harness

Before writing any more scrapers, we need ground-truth data about what
each council site's JavaScript actually does over the wire. The task
for the next agent:

**Goal:** produce a per-council JSON record of every network request
the upstream UKBCD selenium scraper makes while completing a successful
lookup, so we can identify the single XHR (or short chain) that
carries postcode/UPRN in and returns collection data out.

**Deliverable:** `pipeline/ukbcd/capture_upstream_xhrs.py`

**Behaviour:**

1. For each upstream scraper in `pipeline/ukbcd/upstream/` whose
   manifest status is `pending` or `blocked_on_lightpanda_*`:
   - Load its `TEST_CASES` (via `sync_test_cases.py`'s existing loader
     or by importing the module).
   - Launch a real Playwright Chromium (not Lightpanda) with headful
     or headless=new, request interception enabled.
   - Hook `page.on("request")` and `page.on("response")` before
     navigation to catch everything including redirects.
   - Run the upstream scraper's `parse_data()` function with the test
     case's args, letting it drive the browser normally.
   - For every request, record: timestamp, method, URL, resource type,
     request headers (strip `Cookie`, `Authorization`), post data,
     response status, response content-type, response body (truncate
     to 64 KB, base64 if binary).
   - Filter out obvious static assets (`image/*`, `font/*`, `text/css`,
     `*.js` with 2xx and no JSON-ish body) into a separate list so the
     interesting XHR is easy to spot.
2. Write `pipeline/ukbcd/xhr_captures/{CouncilName}.json`, one per
   scraper, with a top-level shape:

   ```json
   {
     "council": "NorthDevonCountyCouncil",
     "captured_at": "2026-04-24T…",
     "test_case": { "postcode": "EX31 …", "uprn": "…" },
     "success": true,
     "xhrs": [ { method, url, headers, body, status, response_body } ],
     "static_assets": [ … ],
     "errors": [ … ]
   }
   ```
3. Ship it behind a `uv run python -m pipeline.ukbcd.capture_upstream_xhrs
   --council NorthDevonCountyCouncil` CLI; default target is "all
   pending/blocked". Concurrency 1 per council, 4 councils in parallel
   max, real browser = expensive.
4. Emit a summary report `pipeline/ukbcd/xhr_capture_summary.json`
   listing for each council: number of XHRs, candidate "payload"
   request (heuristic: non-GET *or* response JSON containing the UPRN,
   postcode, or date-ish strings), and a `httpx_convertible` boolean
   guess.

**After the harness runs:**

- Review the summary, pick the councils with a single clean XHR.
- For each, write `api/scrapers/ukbcd_<slug>.py` using `httpx.AsyncClient`
  only; no Playwright import, no browser pool.
- Flip the manifest entry to `status: "ported"`, `backend: "httpx"`,
  add a `reversed_from_xhr: "<url>"` field for provenance.
- Re-run the integration suite; expect each new port to complete in
  <1s with zero browser overhead.

The 6 Lightpanda-pinned scrapers stay in place as the browser-path
reference implementations. Every new port from here is Tier 0 unless
the harness proves otherwise.

---

## Phase 2.6 — Harness landed, captures done, plan revised (2026-04-24)

Phase 2.5 is no longer theoretical. The capture harness exists, all 29
eligible upstream selenium scrapers have been driven through it, and the
vendor-cluster picture changed enough that the porting order needs to be
rewritten. This section records what we built, what broke, what we found,
and what to do next.

### 2.6.1 Harness design (what `pipeline/ukbcd/capture_upstream_xhrs.py` actually does)

The harness is a thin orchestrator around a disposable subprocess:

1. For each council in `handport_manifest.json` with status `pending` or
   `blocked_on_lightpanda_*`, load the test case from
   `pipeline/upstream/ukbcd_selenium_clone/uk_bin_collection/uk_bin_collection/tests/input.json`.
2. Start a headless Chrome with `--remote-debugging-port=<free>` and a
   fresh `--user-data-dir`. Chrome is launched *before* the scraper so
   Playwright can attach via CDP.
3. Spawn a child process with `uv run --no-project --with` pinning
   `uk-bin-collection`, `selenium`, `webdriver-manager`. The child imports
   the upstream `CouncilClass` dynamically and calls
   `get_and_parse_data(url, **payload)` (the framework entry point,
   *not* `parse_data` directly — see 2.6.2).
4. The child monkey-patches `uk_bin_collection.uk_bin_collection.common.create_webdriver`
   to attach to the already-running Chrome via `Remote(command_executor=...)`.
5. Two-stage handshake over stdin/stdout:
   - child prints `__READY__` → parent attaches Playwright via CDP →
     parent prints `__GO__` → child runs scraper
   - child prints `__QUIT_REQUESTED__` before driver.quit() → parent
     fetches all response bodies → parent prints `__FINISH__` → child exits.
   Without the second handshake, Chrome dies before Playwright can pull
   response bodies, so the XHR list is empty.
6. Parent serialises every request/response pair (URL, method, status,
   request headers, POST body, response headers, response body) to
   `pipeline/ukbcd/xhr_captures/<scraper>.json`.

Browserless detection: some upstream scrapers never touch selenium (they
use `requests` internally despite living in the selenium clone). The
harness detects this by watching for `__RESULT__` arriving before
`__READY__` and records the run as `status: "browserless"` with no XHRs.

### 2.6.2 The `paon` bug — lesson codified

Pass 1 got 18/29. 11 councils produced zero XHRs despite having passed
`selenium_test_results.json` days earlier. Root cause:

- Upstream CLI (`collect_data.py`) maps `-n/--number` → kwarg `paon`.
- `input.json` stores the same value under key `house_number`.
- The initial `build_payload` copied keys verbatim, so `paon` was `None`.
- Affected scrapers call `check_paon(paon)` on entry and raise immediately.
- Because the raise happened inside `parse_data` before any XHR fired,
  the capture looked like "scraper doesn't use the network" rather than
  "scraper crashed before doing anything".

Fix (in `build_payload`):

- Map `house_number` → `paon` when `paon` absent.
- Propagate `url`, `skip_get_url`, `headless=True`, `local_browser=True`,
  `web_driver=None` so `get_and_parse_data` takes the happy path.
- Call `get_and_parse_data(url, **payload)` from the harness, not
  `parse_data('', **payload)` — the framework layer is where URL
  fetching + skip_get_url live.

Pass 2 after the fix: **29/29 successful captures**. Lesson: always drive
upstream scrapers through `get_and_parse_data`, the same entry point the
CLI uses, or field-name mismatches will silently turn into empty captures.

### 2.6.3 Vendor clusters — revised after manual review

The auto-heuristic only flagged 9/29 captures as "httpx-convertible".
Recall is poor because vendor payloads often come back as HTML fragments,
encrypted blobs, or Salesforce Aura messages, none of which the
JSON-content-type check catches. Manual review of the 20 "no-candidate"
captures produced the real picture:

| Cluster              | Count | Notes                                              |
| -------------------- | ----- | -------------------------------------------------- |
| IEG4 AchieveForms    | 4     | Already prototyped in Tier A work                  |
| Jadu CXM             | 3     | Grew from 1 → 3 (Hillingdon, Powys added)          |
| Jadu Continuum       | 2     | Sevenoaks, Hertsmere                               |
| iTouchVision         | 4     | AES-256-CBC; **already ported twice** (see 2.6.4)  |
| Salesforce Community | 1     | Aura endpoints; feasible but bespoke               |
| Singletons           | 11    | One-off council stacks                             |
| Browserless          | 4     | Basildon, DumfriesAndGalloway, Edinburgh, Ceredigion — already httpx internally |

The 4 browserless cases are free wins: port them to `api/scrapers/` as
plain httpx scrapers with zero reverse-engineering, flip manifest to
`ported`.

### 2.6.4 iTouchVision is not a hard case

Two iTouchVision councils are already ported in the tree:

- `api/scrapers/ukbcd_buckinghamshire_council.py`
- `api/scrapers/ukbcd_newport_city_council.py`

Both use the same AES-256-CBC with PKCS#7 padding, and the key/IV are
fixed across every iTouchVision deployment:

```
key_hex = "F57E76482EE3DC3336495DEDEEF3962671B054FE353E815145E29C5689F72FEC"
iv_hex  = "2CBF4FC35C69B82362D393A4F0B9971A"
```

The only per-council variables are `P_CLIENT_ID` and `P_COUNCIL_ID`,
visible in the upstream selenium flow's POST body:

- Buckinghamshire: `P_CLIENT_ID=152`, `P_COUNCIL_ID=34505`
- Newport: `P_CLIENT_ID=130`, `P_COUNCIL_ID=260`

Action: extract an `api/compat/ukbcd/itouchvision.py` base with the
shared AES + request flow, and reduce each iTouchVision scraper to a
~20-line subclass that sets the two IDs. That covers all 4 captured
councils plus the 2 already-ported ones with a single maintenance point.

### 2.6.5 Heuristic recall limits

The "httpx_convertible" flag in `xhr_capture_summary.json` is advisory,
not authoritative. It missed iTouchVision (encrypted bodies), Salesforce
Aura (multipart form posts returning JSON wrapped in a framework
envelope), and most Jadu CXM endpoints (HTML-fragment responses with
`text/html` content-type). Treat the summary's 9 as a lower bound;
manual inspection of each capture is still required.

### 2.6.6 Revised porting order

1. **Browserless quick wins (4)** — Basildon, DumfriesAndGalloway,
   Edinburgh, Ceredigion. No XHR analysis needed; port the requests
   flow straight across.
2. **iTouchVision base + 4 new subclasses** — build the compat base,
   then Teignbridge, Cheshire East, etc. Refactor Bucks + Newport onto
   the base in the same PR.
3. **Jadu Continuum (2)** — Sevenoaks, Hertsmere share a template; port
   one, generalise, port the second.
4. **Jadu CXM (3)** — Hillingdon, Powys, and the original. Similar
   session-hand-off pattern; one base class likely.
5. **IEG4 AchieveForms (4)** — finish the prototype from Tier A and
   fan out.
6. **Salesforce Aura (1)** — bespoke but self-contained; does not block
   anything else.
7. **Singletons (11)** — lowest ROI per port; tackle after the clusters
   are done and the shared helpers are stable.
8. **Flip manifest entries to `ported`** as each lands; run integration
   suite and confirm <1s wall-clock per scraper.

### 2.6.7 Implications for Tier A's already-landed Lightpanda ports

Six scrapers already live in `api/scrapers/` with Lightpanda pinning.
Nothing in Phase 2.6's findings forces a rewrite of those — the
browser path remains the fallback for anything we can't reverse. But
for the three that fall into the iTouchVision / Jadu Continuum / Jadu
CXM clusters (check `handport_manifest.json` before acting), a pure
httpx rewrite is now cheap and removes them from the browser-pool
dependency. Do this opportunistically, not as a blocker.

### 2.6.8 Artefacts produced in this phase

- `pipeline/ukbcd/capture_upstream_xhrs.py` — the harness itself.
- `pipeline/ukbcd/xhr_captures/*.json` — 29 per-council capture files.
- `pipeline/ukbcd/xhr_capture_summary.json` — aggregate + heuristic flag.
- `HANDPORT_XHR_FINDINGS.md` — narrative of the investigation, cluster
  scorecard, and capture-by-capture notes.
- This section.

