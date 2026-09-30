"""Bulk-convert wired api/scrapers/ modules to api/councils/ with one LLM call each.

Every LAD-wired scraper becomes api/councils/<module>.py, named after the
LADs it serves. The prompt carries the _base sources, the hand-converted
examples, any platform module the old scraper relied on, and the old source.
The result is written, ruff-fixed and import-checked; nothing is run against
live sites here (that's `scripts.councils.check`).

    uv run python -m scripts.councils.convert --plan            # print old id -> module
    uv run python -m scripts.councils.convert                   # convert everything not yet converted
    uv run python -m scripts.councils.convert hacs_bury_gov_uk  # just these
    uv run python -m scripts.councils.convert --force ...       # overwrite existing modules

OPENAI_API_KEY comes from the environment, else ../chartreuse/.env.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import ai

ROOT = Path(__file__).resolve().parents[2]
OLD_DIR = ROOT / "api" / "scrapers"
NEW_DIR = ROOT / "api" / "councils"
BASE_DIR = NEW_DIR / "_base"
PLATFORMS_DIR = NEW_DIR / "_platforms"
LAD_LOOKUP = ROOT / "api" / "data" / "lad_lookup.json"
LAD_CASES = ROOT / "tests" / "lad_test_cases.json"
LOG = ROOT / "scripts" / "councils" / "convert_log.json"
MODEL = "openai:gpt-6-luna"

EXAMPLES = ["hartlepool", "adur_and_worthing", "bexley", "lancaster"]
BASE_FILES = ["__init__.py", "scraper.py", "address.py", "http.py", "collection.py", "errors.py",
              "matching.py", "dates.py", "html.py", "ics.py"]

# Old shared helper -> the platform module that replaces it.
PLATFORMS = {
    "api.compat.whitespace": "whitespace",
    "api.compat.hacs.itouchvision": "itouchvision",
    "api.compat.hacs.service.AchieveForms": "achieveforms",
    "api.compat.hacs.service.FirmstepSelfService": "firmstep",
    "api.compat.hacs.service.uk_cloud9_apps": "cloud9",
    "api.compat.ukbcd.councils.SocietyWorks": "societyworks",
}

RULES = """\
You convert one UK council bin-collection scraper from the old `Source` shape to the new
`Scraper` contract defined by the `api.councils._base` sources below. Reply with the complete
new module in a single ```python block and nothing else.

Keep the council's request flow exactly: same URLs, query params, form fields, JSON payloads,
headers and parsing logic. Don't invent endpoints, don't "improve" what the council is sent,
and don't drop fallback branches. What changes is the plumbing:

Shape
- One module: a short docstring describing the council's flow, imports, private module-level
  constants/helpers (leading underscore), one `Scraper` subclass, then `SCRAPER = ClassName()`.
  If the old scraper used a platform helper that has a `_platforms` module (source given), use
  that platform instead, the way `lancaster` uses Whitespace.
- The class is stateless. No `__init__`, nothing stored on `self`; per-lookup values are locals
  or arguments to private helpers/methods.
- ukbcd modules (`CouncilClass(AbstractGetBinDataClass)` + an adapter `Source`) collapse into
  a direct `fetch` that builds `Collection`s. No intermediate {"bins": [...]} dicts and no
  date strings round-tripped through strftime/strptime.
- Import everything from `api.councils._base` (plus stdlib, bs4 types, dateutil, pdfplumber,
  pypdf, cryptography as needed). Never import httpx, requests, curl_cffi or anything from
  `api.compat` / `api.scrapers`.

Meta
- `title` from TITLE, `url` from URL (prefer the council's bin page or homepage over an API
  endpoint when the old URL is an API endpoint), `lads` exactly as given in the task.
- `cases`: at most 3 of the old TEST_CASES, rewritten into the frontend vocabulary: string
  values only, keys among uprn, postcode, house_number, street, address (the full label), plus
  council-specific extras the scraper genuinely needs. A case whose old keys were
  `{"postcode", "address": "1 Western Road North"}` becomes postcode + house_number "1" +
  street "Western Road North". Drop cases that need secrets or credentials. `{}` if none.

Input
- The harness guarantees every name in `requires` before `fetch` runs. Read those with
  `address.need("uprn")` (typed `str`), optional ones with `address.uprn` etc. (`str | None`).
- Old param names map as: uprn/UPRN/uprn_id -> uprn; postcode/post_code -> postcode;
  house_number/number/paon/house_name/name_number -> house_number; street/street_name -> street;
  a free-text `address` meaning the first line -> `address.first_line`; the full label ->
  `address.label`. Any other param (usrn, property_id, ...) -> `address.need("<name>")` and
  listed in `requires`.
- UPRNs arrive without leading zeros. If the council needs 12 digits use `.zfill(12)`, as the
  old code did.
- `requires` is minimal: what the scraper cannot work without. If it can use the UPRN or fall
  back to postcode + text, require nothing and branch in `fetch`, raising InputError when
  neither route is possible.
- Picking the property from a council's address list (select options, JSON results) is
  `match_address(address, candidates, text=..., uprn=...)`; pass `uprn=` whenever the candidate
  carries a UPRN. It raises AddressNotFound itself. Don't hand-roll text matching.

HTTP
- Only the injected `http`. Class-level `headers` for headers the old code sent on every
  request (its HEADERS/User-Agent); per-request `headers=` for the rest. Don't add a
  User-Agent the old code didn't send.
- `transport = Transport.CURL_CFFI` if the old code used curl_cffi_fallback anywhere;
  `verify_tls = False` if it used verify=False.
- Requests raise UpstreamError on 4xx/5xx by default, so delete every raise_for_status().
  Where the old code read status_code, tolerated an error status, or polled, pass `check=False`
  and keep its logic.
- `r.json()`, `r.text`, `r.content`, `r.url` (a str), `r.headers`. For form bodies use
  `data=`, JSON `json=`, raw strings (SOAP/XML) `content=`. Cookies: `http.cookies.set(...)`.
- Blocking work (pdfplumber, pypdf, other sync libraries) goes through `asyncio.to_thread`.
  `time.sleep` becomes `await asyncio.sleep`.

Output and errors
- Return `Collection(date, type)`. Drop ICON_MAP and icon= arguments: the harness assigns
  icons. Keep the old code's type naming (renames, suffix stripping) so types don't change.
- Don't sort or dedupe (the harness does). Keep any date filtering the old code did.
- Dates: keep strptime where the format is fixed. Dates written without a year ("Thursday 1st
  October") go through `parse_date`, replacing hand-rolled year inference.
- Errors: SourceArgumentNotFound*/SourceArgumentException*/"address not found" ValueErrors ->
  AddressNotFound or InputError; site down/blocked -> UpstreamError; captcha, JavaScript-only
  or login walls -> NeedsBrowser. Never `except Exception`; catch the narrow exception you
  expect (ValueError, KeyError, IndexError) when skipping an unparseable row.
- Use `soup(text)` for HTML (html.parser) and `text_of(node)` where a node may be missing.
  Use `parse_ics` for iCalendar feeds.
- Type-clean code: annotate `fetch` exactly like the examples, helper signatures fully.
"""


@dataclass
class Job:
    old_id: str
    module: str
    lads: list[str]
    platform: str | None


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.split(",")[0].lower()).strip("_")


def plan() -> list[Job]:
    lookup = json.loads(LAD_LOOKUP.read_text())
    by_old: dict[str, list[tuple[str, str]]] = {}
    for lad, entry in sorted(lookup.items()):
        if entry.get("scraper_id"):
            by_old.setdefault(entry["scraper_id"], []).append((lad, entry["name"]))
    jobs = []
    for old_id, lads in sorted(by_old.items()):
        source = (OLD_DIR / f"{old_id}.py").read_text()
        platform = next((p for mod, p in PLATFORMS.items() if mod in source), None)
        module = "_and_".join(sorted({_slug(name) for _, name in lads}))
        jobs.append(Job(old_id, module, [lad for lad, _ in lads], platform))
    return jobs


def _fence(name: str, text: str) -> str:
    return f"### {name}\n```python\n{text}\n```\n"


def system_prompt() -> str:
    parts = [RULES, "\n## api.councils._base sources\n"]
    parts += [_fence(f"api/councils/_base/{f}", (BASE_DIR / f).read_text()) for f in BASE_FILES]
    parts.append("\n## Converted examples\n")
    for name in EXAMPLES:
        parts.append(_fence(f"api/councils/{name}.py", (NEW_DIR / f"{name}.py").read_text()))
    parts.append(_fence("api/councils/_platforms/whitespace.py", (PLATFORMS_DIR / "whitespace.py").read_text()))
    return "\n".join(parts)


def user_prompt(job: Job, sample_params: dict | None) -> str:
    parts = [
        f"Convert `api/scrapers/{job.old_id}.py` into `api/councils/{job.module}.py`.",
        f"lads = {tuple(job.lads)!r}",
    ]
    if sample_params:
        parts.append(f"A typical request's params (what `Address.from_params` receives): {json.dumps(sample_params)}")
    if job.platform:
        path = PLATFORMS_DIR / f"{job.platform}.py"
        if path.exists() and job.platform != "whitespace":
            parts.append(_fence(f"api/councils/_platforms/{job.platform}.py", path.read_text()))
    parts.append(_fence(f"api/scrapers/{job.old_id}.py (old)", (OLD_DIR / f"{job.old_id}.py").read_text()))
    return "\n\n".join(parts)


def _extract(text: str) -> str:
    blocks = re.findall(r"```(?:python)?\n(.*?)```", text, re.S)
    if not blocks:
        raise ValueError("no code block in reply")
    return max(blocks, key=len).strip() + "\n"


def _check(module: str) -> str | None:
    """Ruff-fix the file and import it in a subprocess. Returns an error string or None."""
    path = NEW_DIR / f"{module}.py"
    subprocess.run(["uv", "run", "ruff", "check", "--fix", "--quiet", str(path)], cwd=ROOT, capture_output=True)
    proc = subprocess.run(
        [sys.executable, "-c", f"from api.councils._base.discovery import load; load({module!r})"],
        cwd=ROOT, capture_output=True, text=True,
    )
    return proc.stderr.strip().splitlines()[-1] if proc.returncode else None


async def convert(job: Job, model: ai.Model, system: str, sample: dict | None) -> dict:
    started = time.monotonic()
    messages = [ai.system_message(system), ai.user_message(user_prompt(job, sample))]
    try:
        async with ai.stream(model, messages) as s:
            async for _ in s:
                pass
        code = _extract(s.text)
    except Exception as exc:  # noqa: BLE001 - one failed call mustn't stop the batch
        return {**asdict(job), "ok": False, "error": f"{type(exc).__name__}: {exc}"[:300]}
    (NEW_DIR / f"{job.module}.py").write_text(code)
    error = await asyncio.to_thread(_check, job.module)
    usage = s.usage
    return {
        **asdict(job),
        "ok": error is None,
        "error": error,
        "seconds": round(time.monotonic() - started, 1),
        "tokens": [usage.input_tokens, usage.output_tokens] if usage else None,
    }


def _load_key() -> None:
    if os.environ.get("OPENAI_API_KEY"):
        return
    env = ROOT.parent / "chartreuse" / ".env"
    for line in env.read_text().splitlines():
        if line.startswith("OPENAI_API_KEY="):
            os.environ["OPENAI_API_KEY"] = line.split("=", 1)[1].strip().strip("\"'")


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("old_ids", nargs="*")
    ap.add_argument("--plan", action="store_true")
    ap.add_argument("--force", action="store_true", help="overwrite existing modules")
    ap.add_argument("--concurrency", type=int, default=24)
    args = ap.parse_args()

    jobs = plan()
    if args.plan:
        for j in jobs:
            print(f"{j.old_id:<50} {j.module:<40} {','.join(j.lads)} {j.platform or ''}")
        return 0
    if args.old_ids:
        jobs = [j for j in jobs if j.old_id in args.old_ids]
    else:
        # Platform councils are converted alongside their platform, by hand.
        jobs = [j for j in jobs if j.platform is None]
    if not args.force:
        jobs = [j for j in jobs if not (NEW_DIR / f"{j.module}.py").exists()]
    missing_platforms = {j.platform for j in jobs if j.platform and not (PLATFORMS_DIR / f"{j.platform}.py").exists()}
    if missing_platforms:
        skipped = [j for j in jobs if j.platform in missing_platforms]
        jobs = [j for j in jobs if j.platform not in missing_platforms]
        print(f"skipping {len(skipped)} modules whose platform isn't ported yet: {sorted(missing_platforms)}")

    _load_key()
    model = ai.get_model(MODEL)
    system = system_prompt()
    lad_cases = json.loads(LAD_CASES.read_text())
    sem = asyncio.Semaphore(args.concurrency)
    importlib.invalidate_caches()

    async def one(job: Job) -> dict:
        sample = next(
            (c["params"] for c in lad_cases.get(job.lads[0], {}).get("cases", []) if c["source"] == "sampled"),
            None,
        )
        async with sem:
            result = await convert(job, model, system, sample)
        print(("✓" if result["ok"] else "✗"), job.module, result.get("error") or "", flush=True)
        return result

    print(f"converting {len(jobs)} modules with {MODEL}")
    results = await asyncio.gather(*(one(j) for j in jobs))
    previous = json.loads(LOG.read_text()) if LOG.exists() else {}
    previous.update({r["module"]: r for r in results})
    LOG.write_text(json.dumps(previous, indent=1, sort_keys=True))
    ok = sum(r["ok"] for r in results)
    print(f"\n{ok}/{len(results)} converted and importable; log: {LOG.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
