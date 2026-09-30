# Scraper contract: design

Status: draft, 2026-09-30. Nothing is built yet. Next step: hand-convert about 10 varied
scrapers against this design, then revise it before any bulk conversion.

## Why

About 310 scrapers come from three sources (hacs, ukbcd, hand ports). They share one outline,
`Source(**params)` plus `async fetch() -> list[Collection]`, and nothing else. The breakages
from the first run of the sampled-address live test fall into a few families. Each family
comes from something the scraper decides for itself but the platform should own:

| Failure seen in the live run | Root cause | Owned by (below) |
|---|---|---|
| Fixture passes, real address fails (Newcastle, Bury, Charnwood, Rochford, South Norfolk, Greenwich...) | Each scraper chooses its own param names and formats, then matches addresses by exact text; the UPRN we already have is ignored | `Address`, `match_address` |
| `'coroutine' object has no attribute ...` (Slough, Sevenoaks, Hackney) | The requests→httpx AST patcher misses await precedence and sync helpers | Hand-owned async code, type-checked |
| Blocking calls in async `fetch` (Cloud9 client, icalevents, pdf parsing) | Sync libraries called inside the event loop | `run_blocking`, ruff `ASYNC` rules |
| `"x" in response.url` crashes (Havant) | httpx vs curl_cffi responses differ | One `Http`/`Response` interface |
| Silent `[]` (Hackney) | `except Exception: pass` around parsing | Error hierarchy, ruff `BLE001` |
| Real "address not found" reported as `scraper_error` | `ValueError` / custom exceptions don't map to 422 | Error hierarchy |
| Clients never closed (Hartlepool, Crawley, ...) | Each scraper builds its own `httpx.AsyncClient` | Harness owns the client lifecycle |
| Ad-hoc year inference for "Thursday 1st October" (Adur & Worthing) | No shared date helpers | `dates` helpers |

## Public contract that must not change

- Query keys the frontend sends to `/lookup/{uprn}` and `/calendar/{uprn}`: `council`,
  `postcode`, `address` (comma-joined label), `house_number`, `street`, plus the UPRN in the
  path. These are baked into ICS subscription URLs already sitting in users' calendars.
- `council=<scraper_id>` in those URLs, and `scraper` + `params` in every ICS sidecar
  (the refresh job re-invokes with the stored params). Any rename needs aliases (see IDs).
- The output `Collection` fields the cache reads: `date`, `type`, `icon`.
- 422 / 503 / 504 semantics and messages in `scrape_orchestrator.map_scrape_exception`.

## The contract

A new package, `api/councils/`, with the framework in `api/councils/_base/`. Each council
module exposes one module-level `SCRAPER`.

### Input: `Address`

Built once, by the orchestrator, from the query params. Scrapers never parse the query
string or the joined label.

```python
@dataclass(frozen=True)
class Address:
    uprn: str | None            # digits only, leading zeros stripped; None for "0"/placeholders
    postcode: str | None        # normalised "NE3 4JJ"
    house_number: str | None    # PAON as the address API gives it: "47", "47A", "Flat 2", "Rose Cottage"
    street: str | None
    label: str | None           # the frontend's full "47, Montagu Avenue, Newcastle Upon Tyne, NE3 4JJ"
    extra: Mapping[str, str]    # council-specific keys (usrn, property_id, calendar_number...)

    @property
    def first_line(self) -> str | None: ...        # "47 Montagu Avenue" (subsumes api/compat/address.py)
    @property
    def postcode_compact(self) -> str | None: ...  # "NE34JJ"

    @classmethod
    def from_params(cls, params: Mapping[str, str]) -> Address: ...
```

`from_params` is the only place the frontend's format is known. Old fixture shapes
(Stirling's `house_number="5 Sunnylaw Road"`, the `paon` alias in ukbcd) get rewritten
into proper fields during conversion, not tolerated at runtime.

### Declaring what a scraper needs

```python
Field = Literal["uprn", "postcode", "house_number", "street", "label"]

requires: frozenset[Field | str]   # e.g. {"uprn"}, {"postcode", "house_number"}, {"usrn"}
```

This replaces introspecting `Source.__init__`. The registry derives the `/councils`
required/optional metadata and the missing-param 422 from it. `fixture_only` in the live
test becomes "`requires` includes a key the frontend never sends", so it stops being guessed.

Keep `requires` minimal. A scraper that prefers the UPRN but can fall back to text requires
what it can't work without and handles the fallback in its body. No "one of" DSL.

### The scraper

```python
@dataclass(frozen=True)
class Meta:
    title: str                           # "Hartlepool Borough Council"
    url: str                             # council page, used for admin lookup + deeplinks
    cases: Mapping[str, Mapping[str, str]]  # fixtures, in the frontend's param vocabulary

class Scraper(ABC):
    meta: Meta
    requires: frozenset[str]
    transport: Transport = Transport.HTTPX     # or CURL_CFFI (TLS impersonation)
    verify_tls: bool = True

    @abstractmethod
    async def fetch(self, address: Address, http: Http) -> list[Collection]: ...
```

- No `__init__` per request. A scraper is a stateless object; per-request state lives in
  locals. That lets platform scrapers be instances of one class with different config.
- `transport` and `verify_tls` replace `patch_overrides.json`'s `curl_cffi_fallback` /
  `ssl_verify_disabled` source rewriting. They're class attributes the harness reads.
- `requests_fallback` has zero users left; it goes.

Two shapes of module:

```python
# Bespoke council
class Hartlepool(Scraper):
    meta = Meta(title="Hartlepool Borough Council", url="https://www.hartlepool.gov.uk",
                cases={"Test_001": {"uprn": "100110021946"}})
    requires = frozenset({"uprn"})

    async def fetch(self, address, http):
        ...

SCRAPER = Hartlepool()

# Council on a shared platform
SCRAPER = WhitespaceWRP(
    Meta(title="Lancaster City Council", url="https://lancaster.gov.uk", cases={...}),
    WhitespaceConfig(base_url="https://lcc-wrp.whitespacews.com", ...),
)
```

Platform classes (`WhitespaceWRP`, `AchieveForms`, `Bartec`, `ReCollect`, `ITouchVision`,
`FirmstepSelfService`, `Cloud9`, `SocietyWorks`...) live in `api/councils/_platforms/`.
Each is a `Scraper` subclass taking a frozen config dataclass. `api/compat/whitespace.py`
is already this shape and becomes the first one.

### HTTP: `Http`, injected

```python
class Http(Protocol):
    async def get(self, url: str, **kw) -> Response: ...
    async def post(self, url: str, **kw) -> Response: ...
    async def request(self, method: str, url: str, **kw) -> Response: ...

class Response(Protocol):
    status_code: int
    url: str            # always str, whatever the backend
    text: str
    content: bytes
    headers: Mapping[str, str]
    def json(self) -> Any: ...
    def raise_for_status(self) -> None: ...   # raises UpstreamError
```

- The harness builds one `Http` per invocation (cookie jar per request, as the scrapers
  expect), sets a default browser UA and timeouts, and closes it afterwards. Scrapers never
  construct clients.
- Backends: httpx, curl_cffi (the shared session and semaphore from
  `curl_cffi_fallback.py`), and **record** / **replay**. The last two are what make bulk
  conversion checkable (see Migration). They exist because of that, not as an extension point.
- `run_blocking(fn, *args)` (thin `asyncio.to_thread`) for pdfplumber, pypdf, icalevents.

### Errors

```python
class ScraperError(Exception): ...          # base; anything else unhandled is a bug

class InputError(ScraperError): ...         # 422: the council rejects what we sent
class AddressNotFound(InputError): ...      #      carries suggestions when the site offers them
class UpstreamError(ScraperError): ...      # 503: council site down / HTTP error / blocked
class NeedsBrowser(ScraperError): ...       # captcha, JS-only, login: a deeplink candidate
```

- `map_scrape_exception` maps these types directly. It keeps accepting
  `httpx.HTTPError` / `SourceArgument*` while old-style scrapers exist.
- `Response.raise_for_status` and connection failures in `Http` raise `UpstreamError`, so
  scrapers don't need to know the backend's exception types.
- An empty result is legal (some addresses genuinely have no service) and stays the live
  test's `empty` outcome. Swallowing is not: ruff `BLE001` (blind except) is on for the
  package, so `except Exception: pass` doesn't lint.
- `NeedsBrowser` gives Coventry, Havant and the like a truthful state instead of
  `scraper_error`. It routes automatically: the orchestrator answers with the same deeplink
  response `deeplinks.py` serves today (council name, reason, the scraper's `meta.url` or the
  LAD's GOV.UK waste URL). The live test records it as its own outcome, and those LADs show
  as "deeplink" rather than broken. A scraper that knows it can never work without a browser
  can declare `needs_browser = True` and skip the request entirely.

### Output

`Collection` stays dict-shaped (`date`, `type`, `icon`) so `ics_cache` is unchanged. It moves
from `api/compat/hacs/collection.py` to `api/councils/_base/` and loses the HA-only parts
(`picture`, `daysTo`, `CollectionGroup`) once nothing imports them.

The harness, not each scraper, post-processes: dedupe on `(date, type)`, sort by date,
strip whitespace from types. It doesn't filter by date; the cache already prunes by
`ICS_RETENTION_DAYS`.

Icons: each scraper keeps an optional `icons` map. A shared default keyed on common words
(refuse / recycling / garden / food / glass) fills the gaps. It's worth doing because 300 copies
of `ICON_MAP` currently disagree.

### Shared helpers (`api/councils/_base/`)

Only the ones the live failures and a grep show are needed repeatedly:

- `match_address(address, candidates, *, uprn=..., text=...)`: UPRN first (leading zeros
  ignored), then `first_line`, then house number + street prefix, else `AddressNotFound`
  with the candidate labels as suggestions. This one function would have fixed most of the
  "fixture passes, sampled fails" group.
- `dates.parse_uk(text, today)`: "Thu 1st October", "01/10/2026", "1 Oct" with year
  inference (roll forward when the date is in the past); `next_weekday(...)`.
- `html.soup(text)`: one BeautifulSoup parser choice.

Not in scope: a template-method pipeline (`search()` → `select()` → `parse()`). PDF, ICS,
form and JSON councils don't share those steps, and forcing them adds indirection and
nothing else.

### Registry

- Discovers `api/councils/*.py`, reads `SCRAPER`, builds `ScraperMeta` from `meta` and
  `requires`.
- `invoke(scraper_id, params)`: `Address.from_params(params)` → check `requires` →
  open `Http` for the declared transport → `await wait_for(fetch(...), SCRAPER_TIMEOUT)` →
  post-process → close.
- During migration it loads both `api/scrapers/*.py` (`Source`) and `api/councils/*.py`
  (`SCRAPER`), with a new module shadowing the old one of the same ID. Tests and the
  frontend don't change while conversion is in flight.

### IDs: the ONS LAD code

Today's IDs (`hacs_south_norfolk_and_broadland_gov_uk`, `ukbcd_...`, `port_...`) encode
provenance, which is meaningless once upstream is cut. The new ID is the LAD code
(`E07000144`), which `postcode_lookup.parquet` already returns:

- `lad_lookup.json` maps each LAD to at most one scraper today, so the code is a valid key.
  `pipeline/data/scraper_lad_map.json` and `lad_overrides.json`'s wiring go away: a module
  *declares* the LADs it serves.
- Module files keep readable names (`api/councils/south_norfolk_and_broadland.py`) for
  navigation. Each declares `lads = ("E07000144", "E07000149")`, and the registry registers the
  scraper under every listed code. Two LADs sharing one implementation (Adur & Worthing,
  South Norfolk & Broadland) is one module, not two.
- The registry rejects two modules claiming the same LAD. It also rejects a claimed code
  that isn't in `lad_base.json`, so a typo or stale code fails at startup rather than silently
  unwiring a council.
- `api/councils/_aliases.json` maps old scraper IDs, and recoded LAD codes (East Herts
  `E07000097` → `E07000242`), to current codes. The registry resolves aliases on lookup, so
  existing calendar URLs (`council=hacs_...`) and cache sidecars keep working. The ICS
  cache's same-scraper check compares resolved IDs. Old scraper IDs that served two LADs
  alias to either one, since the implementation is identical. Aliases are never removed:
  calendar URLs live forever.
- A future reorganisation (a merger into a new unitary) is an edit to `lads` plus an alias,
  in one place.

### Tooling that now applies

Since the code is ours:

- ruff over `api/councils/` including `ASYNC` (blocking calls in async), `BLE001`, `B`.
- pyright (basic) over `api/councils/`. Un-awaited coroutines (`'coroutine' object has
  no attribute`) are type errors, which catches the whole Slough/Sevenoaks/Hackney class
  statically.

## Migration plan

1. **Framework + 10 hand conversions.** Pick for spread: one Whitespace (config), one
   AchieveForms, one curl_cffi, one PDF, one ICS, one multi-LAD (South Norfolk & Broadland),
   one address-text match (Newcastle / ReCollect), one ukbcd `AbstractGetBinDataClass`, one
   plain UPRN JSON (Hartlepool), one `NeedsBrowser`. Revise this doc from what hurts.
2. **Record.** Run every existing scraper on every case (sampled + fixture) through the
   record backend. Store the HTTP exchanges and the parsed `(date, type)` list per case
   under `tests/cassettes/<new_id>/`. That output is the golden baseline, bugs included.
3. **Platforms.** Fold each platform cluster (AchieveForms ~28, Whitespace ~23, Bartec
   ~16, ReCollect ~12, iTouchVision ~9) into one `_platforms/` class plus config modules.
   Verify each against the cassettes.
4. **Bulk convert the long tail.** One LLM call per module, batched by family. The prompt
   carries this doc, the `_base` API, and 2–3 converted examples from the same family.
   Gate: replaying the recorded HTTP exchanges must give identical output. Mismatches go to an
   agent loop with the replay test as the oracle. Intentional behaviour changes (bug
   fixes) are allowed only with the golden output updated in the same change.
5. **Live run**, then `post_integration.sh`.
6. **Cut upstream.** Delete `api/scrapers/`, `pipeline/hacs/`, `pipeline/ukbcd/`,
   `pipeline/ports/`, `pipeline/sync_all.py`, `patch_overrides.json`, `api/compat/hacs/`,
   `api/compat/ukbcd/`. Keep `pipeline/data/*` and the LAD tooling. Add a monthly job that
   diffs upstream for councils we cover and opens an issue when one changes. Keep upstream
   attribution and licence notices.

### Cassettes

Committed, under `tests/cassettes/<module>/<case_id>.json`. They're test data, so churn is
the main cost, and the recorder is built to avoid it:

- **Write only on change.** Serialise deterministically (sorted keys, stable ordering,
  bodies as text where decodable), compare with the file on disk, and leave it untouched
  when equal. Re-recording a working council produces no diff.
- **Never overwrite a good cassette with a bad one.** A case whose recording ends in an
  error or an empty result keeps its previous cassette. The failure is reported, not
  written.
- **Mask volatile values** before comparing: session tokens, CSRF fields, cookies,
  `_=<epoch>` params, `Date` headers. Otherwise every recording differs.
- **Record on demand**, per module (`--only E07000144`), never as a side effect of the
  live test. A full re-record is an explicit command.
- **Binary bodies** (the ~7 PDF scrapers) are stored once per distinct file, keyed by
  content hash (`tests/cassettes/_blobs/<sha256>`), and the cassette references the hash.
  Councils serve the same calendar PDF for many addresses, so it's stored once, and an
  unchanged PDF never re-commits. The repo doesn't use Git LFS, and this doesn't need it.

Replay caveat: scrapers that put `now()` in a request (timestamps, date ranges) won't
replay byte-identically. Replay matches on method + URL path + body with the same volatile
values masked, and the harness freezes `today` during replay.

## Decisions

- IDs are ONS LAD codes, with permanent aliases for old scraper IDs and recoded LADs.
- `NeedsBrowser` routes to a deeplink automatically.
- Cassettes are committed; the recorder writes only on change and never replaces a good
  recording with a failed one.
