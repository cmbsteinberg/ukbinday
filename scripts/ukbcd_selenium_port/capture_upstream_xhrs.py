#!/usr/bin/env python3
"""Capture upstream UKBCD selenium scraper network traffic.

For each selenium scraper marked ``pending`` or ``blocked_on_lightpanda_*`` in
``handport_manifest.json``, run the upstream ``parse_data()`` in a disposable
``uv run`` venv with selenium. The subprocess launches Chrome with
``--remote-debugging-port``; this parent process attaches Playwright over CDP
to the same browser and records every request/response.

Outputs:
  * ``scripts/ukbcd_selenium_port/xhr_captures/{Council}.json`` -- full capture per council
  * ``scripts/ukbcd_selenium_port/xhr_capture_summary.json``    -- digest across all runs

Usage::

    uv run python -m scripts.ukbcd_selenium_port.capture_upstream_xhrs                  # all eligible
    uv run python -m scripts.ukbcd_selenium_port.capture_upstream_xhrs --council X,Y    # subset
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import logging
import os
import re
import socket
import sys
import tempfile
import textwrap
import time
from datetime import datetime, timezone
from pathlib import Path

from playwright.async_api import Request, Response, async_playwright

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("capture_upstream_xhrs")

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent
PIPELINE_DIR = PROJECT_ROOT / "pipeline"
UPSTREAM_DIR = PIPELINE_DIR / "upstream" / "ukbcd_selenium_clone"
MANIFEST_PATH = SCRIPT_DIR / "selenium_manifest.json"
COUNCILS_DIR = UPSTREAM_DIR / "uk_bin_collection" / "uk_bin_collection" / "councils"
CAPTURES_DIR = SCRIPT_DIR / "xhr_captures"
SUMMARY_PATH = SCRIPT_DIR / "xhr_capture_summary.json"

REPO = "robbrad/UKBinCollectionData"
BRANCH = "master"

PER_COUNCIL_TIMEOUT_S = 300
READY_TIMEOUT_S = 120
QUIT_TIMEOUT_S = 120
MAX_PARALLEL = 4
MAX_BODY_BYTES = 64 * 1024

STATIC_RESOURCE_TYPES = {"stylesheet", "image", "font", "media"}
STATIC_URL_RE = re.compile(
    r"\.(css|png|jpe?g|gif|webp|svg|ico|woff2?|ttf|otf|mp4|webm)(\?|$)", re.I
)

SENSITIVE_HEADERS = {"cookie", "set-cookie", "authorization", "proxy-authorization"}

UV_DEPS = [
    "selenium",
    "webdriver-manager",
    "beautifulsoup4",
    "bs4",
    "lxml",
    "python-dateutil",
    "requests",
    "urllib3",
    "icalendar",
    "jsonschema",
    "holidays",
    "pandas",
    "tabulate",
]

# ---------------------------------------------------------------------------
# Subprocess harness (runs inside uv-managed venv)
# ---------------------------------------------------------------------------

HARNESS = textwrap.dedent(
    """
    import json, os, sys, traceback

    council = sys.argv[1]
    port = sys.argv[2]
    user_data_dir = sys.argv[3]
    payload = json.loads(sys.argv[4])
    upstream_root = sys.argv[5]

    sys.path.insert(0, upstream_root)

    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.remote import webdriver as rwd

    def make_options(headless):
        opts = Options()
        if headless:
            opts.add_argument('--headless=new')
        opts.add_argument('--no-sandbox')
        opts.add_argument('--disable-gpu')
        opts.add_argument('--disable-dev-shm-usage')
        opts.add_argument('--window-size=1920,1080')
        opts.add_argument('--remote-debugging-port=' + port)
        opts.add_argument('--user-data-dir=' + user_data_dir)
        opts.add_experimental_option('excludeSwitches', ['enable-logging'])
        return opts

    def _patched_create_webdriver(web_driver=None, headless=True, user_agent=None, session_name=None):
        driver = webdriver.Chrome(options=make_options(headless))
        try:
            driver.set_window_position(0, 0)
        except Exception:
            pass
        sys.stdout.write('__READY__\\n')
        sys.stdout.flush()
        ack = sys.stdin.readline().strip()
        if ack != 'GO':
            raise SystemExit('parent did not ack READY (got: %r)' % ack)
        return driver

    # Patch common module (canonical location) and be defensive about wildcard imports.
    import uk_bin_collection.uk_bin_collection.common as common_mod
    common_mod.create_webdriver = _patched_create_webdriver

    # Pause driver.quit() so the parent can fetch response bodies before Chrome dies.
    _orig_quit = rwd.WebDriver.quit
    def _patched_quit(self):
        try:
            sys.stdout.write('__QUIT_REQUESTED__\\n')
            sys.stdout.flush()
            ack = sys.stdin.readline().strip()
        except Exception:
            ack = 'FINISH'
        try:
            _orig_quit(self)
        finally:
            sys.stdout.write('__QUIT_DONE__\\n')
            sys.stdout.flush()
    rwd.WebDriver.quit = _patched_quit

    # Load the council module, re-patching the module-level reference if it
    # was pulled in via `from ...common import *`.
    mod_path = 'uk_bin_collection.uk_bin_collection.councils.' + council
    module = __import__(mod_path, fromlist=['CouncilClass'])
    if hasattr(module, 'create_webdriver'):
        module.create_webdriver = _patched_create_webdriver

    CouncilClass = getattr(module, 'CouncilClass')

    address_url = payload.pop('url', '') or ''
    result_obj = None
    error_msg = None
    try:
        # Mirror collect_data.py: go through the framework's get_and_parse_data
        # so get_data(url) pre-fetch + skip_get_url + url kwarg behave exactly
        # like the upstream CLI.
        result_obj = CouncilClass().get_and_parse_data(address_url, **payload)
    except SystemExit:
        raise
    except BaseException as e:
        error_msg = ''.join(traceback.format_exception(type(e), e, e.__traceback__))

    envelope = {'result': result_obj, 'error': error_msg}
    sys.stdout.write('__RESULT__' + json.dumps(envelope, default=str) + '\\n')
    sys.stdout.flush()
    """
).strip()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def find_free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def sanitize_headers(headers: dict[str, str]) -> dict[str, str]:
    return {k: v for k, v in headers.items() if k.lower() not in SENSITIVE_HEADERS}


def is_static_asset(url: str, resource_type: str, content_type: str) -> bool:
    if resource_type in STATIC_RESOURCE_TYPES:
        return True
    if STATIC_URL_RE.search(url):
        return True
    if content_type.startswith(("image/", "font/", "text/css")):
        return True
    return False


def ensure_upstream_clone() -> Path:
    """Shallow-clone upstream into a stable path so re-runs are cheap."""
    import subprocess
    if UPSTREAM_DIR.exists() and (UPSTREAM_DIR / ".git").exists():
        logger.info("Reusing existing upstream clone at %s", UPSTREAM_DIR)
        subprocess.run(
            ["git", "-C", str(UPSTREAM_DIR), "fetch", "--depth", "1", "origin", BRANCH],
            check=True, capture_output=True,
        )
        subprocess.run(
            ["git", "-C", str(UPSTREAM_DIR), "reset", "--hard", f"origin/{BRANCH}"],
            check=True, capture_output=True,
        )
        return UPSTREAM_DIR
    UPSTREAM_DIR.parent.mkdir(parents=True, exist_ok=True)
    logger.info("Cloning %s into %s", REPO, UPSTREAM_DIR)
    subprocess.run(
        ["git", "clone", "--depth", "1", "--branch", BRANCH,
         f"https://github.com/{REPO}.git", str(UPSTREAM_DIR)],
        check=True,
    )
    return UPSTREAM_DIR


def load_manifest() -> dict[str, dict]:
    """Load selenium_manifest.json written by the sync pipeline."""
    if not MANIFEST_PATH.exists():
        logger.error("Manifest not found at %s -- run pipeline/ukbcd/sync.sh first", MANIFEST_PATH)
        sys.exit(1)
    return json.loads(MANIFEST_PATH.read_text())


def build_payload(data: dict) -> dict:
    """Mirror what upstream's collect_data.py CLI passes to parse_data.

    The CLI's argparse maps `-n/--number` to the `paon` kwarg, but input.json
    stores the same value under the key `house_number`. Scrapers read
    `kwargs.get('paon')` and `check_paon(None)` raises -- so mapping this
    correctly is load-bearing. Also thread through `url`, `skip_get_url`, and
    `local_browser` so the framework's get_data() + skip_get_url branches behave
    exactly as they do under the CLI."""
    payload: dict = {}
    if data.get("uprn") is not None:
        payload["uprn"] = str(data["uprn"])
    if data.get("postcode") is not None:
        payload["postcode"] = data["postcode"]
    if data.get("usrn") is not None:
        payload["usrn"] = str(data["usrn"])
    paon = (
        data.get("paon") if data.get("paon") is not None else data.get("house_number")
    )
    if paon is not None:
        payload["paon"] = paon
    if data.get("url"):
        payload["url"] = data["url"]
    if "skip_get_url" in data:
        payload["skip_get_url"] = bool(data["skip_get_url"])
    payload["headless"] = True
    payload["web_driver"] = None
    payload["local_browser"] = True
    return payload


def eligible_councils(
    manifest: dict, only: set[str] | None
) -> list[tuple[str, dict]]:
    out: list[tuple[str, dict]] = []
    for council, entry in manifest.items():
        if only and council not in only:
            continue
        data = entry.get("input_data")
        if not isinstance(data, dict):
            logger.warning("[%s] no input_data in manifest, skipping", council)
            continue
        if not (COUNCILS_DIR / f"{council}.py").exists():
            logger.warning("[%s] upstream file missing, skipping", council)
            continue
        out.append((council, data))
    return out


# ---------------------------------------------------------------------------
# Capture
# ---------------------------------------------------------------------------


async def _read_until(
    stream: asyncio.StreamReader,
    buf: list[bytes],
    stop_markers: tuple[str, ...],
    timeout: float,
) -> str | None:
    """Read stdout lines until one starts with any marker in stop_markers.

    Returns the matched marker prefix, or None on timeout/EOF. All consumed
    bytes are appended to buf verbatim so the full transcript is preserved."""
    deadline = asyncio.get_event_loop().time() + timeout
    while True:
        remaining = deadline - asyncio.get_event_loop().time()
        if remaining <= 0:
            return None
        try:
            line = await asyncio.wait_for(stream.readline(), timeout=remaining)
        except asyncio.TimeoutError:
            return None
        if not line:
            return None
        buf.append(line)
        text = line.decode(errors="replace").rstrip("\n")
        for marker in stop_markers:
            if text == marker or text.startswith(marker):
                return marker


async def capture_one(
    council: str,
    data: dict,
    sem: asyncio.Semaphore,
) -> dict:
    async with sem:
        return await _capture_inner(council, data)


async def _capture_inner(council: str, data: dict) -> dict:
    started = time.monotonic()
    payload = build_payload(data)
    port = find_free_port()
    tmp_profile = tempfile.mkdtemp(prefix=f"chrome-{council}-")

    env = os.environ.copy()
    env["PYTHONPATH"] = (
        str(UPSTREAM_DIR)
        + os.pathsep
        + str(UPSTREAM_DIR / "uk_bin_collection")
        + os.pathsep
        + env.get("PYTHONPATH", "")
    )
    env.setdefault("HOME", tmp_profile)

    cmd: list[str] = ["uv", "run", "--no-project"]
    for dep in UV_DEPS:
        cmd += ["--with", dep]
    cmd += [
        "python",
        "-c",
        HARNESS,
        council,
        str(port),
        tmp_profile,
        json.dumps(payload),
        str(UPSTREAM_DIR),
    ]

    logger.info("[%s] launching (port=%d)", council, port)
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=str(UPSTREAM_DIR),
        env=env,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    stdout_buf: list[bytes] = []

    # Step 1: wait for READY (Chrome is up, remote-debug port is open) OR
    # __RESULT__ -- some upstream scrapers never create a webdriver at all
    # (e.g. BasildonCouncil drives a plain requests.post to an Azure API). In
    # that case there is no browser traffic to capture; we still record the
    # scraper result and flag the capture as browserless.
    marker = await _read_until(
        proc.stdout,
        stdout_buf,
        ("__READY__", "__RESULT__"),
        timeout=READY_TIMEOUT_S,
    )
    if marker is None:
        return await _abort(
            proc, council, started, "no __READY__ from harness", stdout_buf
        )
    if marker == "__RESULT__":
        return await _handle_browserless(
            proc, council, data, payload, started, stdout_buf
        )

    # Step 2: attach Playwright.
    events: list[dict] = []
    body_tasks: list[asyncio.Task] = []
    errors: list[str] = []

    async with async_playwright() as p:
        try:
            browser = await p.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
        except Exception as e:
            return await _abort(
                proc, council, started, f"CDP connect failed: {e}", stdout_buf
            )

        def on_request(req: Request):
            try:
                events.append(
                    {
                        "phase": "request",
                        "ts": datetime.now(timezone.utc).isoformat(),
                        "method": req.method,
                        "url": req.url,
                        "resource_type": req.resource_type,
                        "headers": sanitize_headers(req.headers),
                        "post_data": (req.post_data or "")[:MAX_BODY_BYTES]
                        if req.post_data
                        else None,
                        "is_navigation": req.is_navigation_request(),
                        "frame_url": req.frame.url if req.frame else None,
                    }
                )
            except Exception as e:
                errors.append(f"request-handler: {e}")

        async def fetch_body(resp: Response, record: dict):
            try:
                body = await resp.body()
            except Exception as e:
                record["body_error"] = str(e)
                return
            if not body:
                record["body_base64"] = None
                record["body_bytes"] = 0
                return
            record["body_bytes"] = len(body)
            clipped = body[:MAX_BODY_BYTES]
            ct = record.get("headers", {}).get("content-type", "")
            if any(t in ct for t in ("json", "text", "xml", "javascript", "html")):
                try:
                    record["body"] = clipped.decode("utf-8", errors="replace")
                except Exception:
                    record["body_base64"] = base64.b64encode(clipped).decode()
            else:
                record["body_base64"] = base64.b64encode(clipped).decode()

        def on_response(resp: Response):
            try:
                headers = sanitize_headers(resp.headers)
                record = {
                    "phase": "response",
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "url": resp.url,
                    "status": resp.status,
                    "headers": headers,
                    "from_service_worker": resp.from_service_worker,
                }
                events.append(record)
                body_tasks.append(asyncio.create_task(fetch_body(resp, record)))
            except Exception as e:
                errors.append(f"response-handler: {e}")

        def attach(ctx):
            ctx.on("request", on_request)
            ctx.on("response", on_response)

        for ctx in browser.contexts:
            attach(ctx)
        # Future contexts (rare with a CDP attach, but safe).
        browser.on("context", attach)

        # Step 3: tell harness to proceed.
        proc.stdin.write(b"GO\n")
        await proc.stdin.drain()

        # Step 4: wait until harness signals quit-requested (parse_data has returned
        # and driver.quit() has been intercepted). Bodies still fetchable here.
        quit_req = await _read_until(
            proc.stdout,
            stdout_buf,
            ("__QUIT_REQUESTED__",),
            timeout=PER_COUNCIL_TIMEOUT_S,
        )

        if quit_req is not None:
            # Drain outstanding body fetches while Chrome is still alive.
            if body_tasks:
                done, pending = await asyncio.wait(body_tasks, timeout=30)
                for t in pending:
                    t.cancel()

        # Step 5: allow harness to actually quit Chrome.
        try:
            proc.stdin.write(b"FINISH\n")
            await proc.stdin.drain()
        except Exception:
            pass

        try:
            await browser.close()
        except Exception:
            pass

    # Step 6: collect remaining stdout/stderr and surface the result envelope.
    try:
        remaining_stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=QUIT_TIMEOUT_S
        )
    except asyncio.TimeoutError:
        proc.kill()
        remaining_stdout, stderr = await proc.communicate()
        errors.append("subprocess did not exit after FINISH")

    full_stdout = (b"".join(stdout_buf) + remaining_stdout).decode(errors="replace")
    stderr_text = stderr.decode(errors="replace")

    result_obj, harness_error = _extract_result(full_stdout)
    if harness_error:
        errors.append(f"harness: {harness_error}")
    success = (
        bool(result_obj)
        and isinstance(result_obj, dict)
        and bool(result_obj.get("bins"))
    )

    return _finalize(
        council=council,
        data=data,
        payload=payload,
        events=events,
        success=success,
        result=result_obj,
        errors=errors,
        stdout_tail=full_stdout[-4000:],
        stderr_tail=stderr_text[-4000:],
        duration_s=time.monotonic() - started,
        returncode=proc.returncode,
    )


async def _handle_browserless(
    proc, council, data, payload, started, stdout_buf
) -> dict:
    """Upstream scraper completed without ever calling create_webdriver.

    __RESULT__ has already landed in stdout_buf; drain the rest of the process
    and emit a capture with no XHRs and a browserless=True flag. These councils
    are already Tier 0 (plain HTTP) and a good candidate to port as-is."""
    logger.info(
        "[%s] browserless upstream scraper (no selenium) -- recording result-only capture",
        council,
    )
    try:
        remaining_stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=30
        )
    except asyncio.TimeoutError:
        proc.kill()
        remaining_stdout, stderr = await proc.communicate()
    full_stdout = (b"".join(stdout_buf) + remaining_stdout).decode(errors="replace")
    stderr_text = stderr.decode(errors="replace")
    result_obj, harness_error = _extract_result(full_stdout)
    success = (
        bool(result_obj)
        and isinstance(result_obj, dict)
        and bool(result_obj.get("bins"))
    )
    errors = []
    if harness_error:
        errors.append(f"harness: {harness_error}")
    capture = _finalize(
        council=council,
        data=data,
        payload=payload,
        events=[],
        success=success,
        result=result_obj,
        errors=errors,
        stdout_tail=full_stdout[-4000:],
        stderr_tail=stderr_text[-4000:],
        duration_s=time.monotonic() - started,
        returncode=proc.returncode,
    )
    capture["browserless"] = True
    return capture


async def _abort(proc, council, started, reason, stdout_buf) -> dict:
    logger.error("[%s] aborting: %s", council, reason)
    try:
        proc.kill()
    except Exception:
        pass
    try:
        extra_stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=10)
    except Exception:
        extra_stdout, stderr = b"", b""
    stdout = (b"".join(stdout_buf) + extra_stdout).decode(errors="replace")
    return {
        "council": council,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "success": False,
        "xhrs": [],
        "static_assets": [],
        "errors": [reason],
        "stdout_tail": stdout[-4000:],
        "stderr_tail": stderr.decode(errors="replace")[-4000:],
        "duration_s": time.monotonic() - started,
    }


def _extract_result(stdout: str) -> tuple[dict | None, str | None]:
    for line in reversed(stdout.splitlines()):
        if line.startswith("__RESULT__"):
            try:
                envelope = json.loads(line[len("__RESULT__") :])
            except json.JSONDecodeError as e:
                return None, f"result decode: {e}"
            return envelope.get("result"), envelope.get("error")
    return None, "no __RESULT__ line emitted"


def _finalize(
    *,
    council: str,
    data: dict,
    payload: dict,
    events: list[dict],
    success: bool,
    result: dict | None,
    errors: list[str],
    stdout_tail: str,
    stderr_tail: str,
    duration_s: float,
    returncode: int | None,
) -> dict:
    # Pair requests with their responses by URL+method (best-effort; CDP gives
    # each request a unique id but Playwright's Request object is what we have).
    xhrs: list[dict] = []
    static_assets: list[dict] = []
    # Build index of responses by url (first match wins for each method).
    pending_requests: list[dict] = []
    for ev in events:
        if ev["phase"] == "request":
            pending_requests.append(ev)
        elif ev["phase"] == "response":
            match = None
            for req in pending_requests:
                if req["url"] == ev["url"]:
                    match = req
                    break
            if match is not None:
                pending_requests.remove(match)
            rec = {
                "method": (match or {}).get("method", "GET"),
                "url": ev["url"],
                "resource_type": (match or {}).get("resource_type", ""),
                "request_headers": (match or {}).get("headers", {}),
                "post_data": (match or {}).get("post_data"),
                "status": ev["status"],
                "response_headers": ev["headers"],
                "body": ev.get("body"),
                "body_base64": ev.get("body_base64"),
                "body_bytes": ev.get("body_bytes"),
                "body_error": ev.get("body_error"),
                "is_navigation": (match or {}).get("is_navigation", False),
                "frame_url": (match or {}).get("frame_url"),
            }
            ct = rec["response_headers"].get("content-type", "")
            if is_static_asset(rec["url"], rec["resource_type"], ct):
                static_assets.append(
                    {
                        "method": rec["method"],
                        "url": rec["url"],
                        "status": rec["status"],
                    }
                )
            else:
                xhrs.append(rec)

    # Requests without responses (aborted / still in flight).
    for req in pending_requests:
        ct = ""
        rec = {
            "method": req["method"],
            "url": req["url"],
            "resource_type": req["resource_type"],
            "request_headers": req["headers"],
            "post_data": req.get("post_data"),
            "status": None,
            "response_headers": {},
            "body": None,
            "body_bytes": None,
            "is_navigation": req["is_navigation"],
            "frame_url": req.get("frame_url"),
            "note": "no response recorded",
        }
        if is_static_asset(req["url"], req["resource_type"], ct):
            static_assets.append(
                {"method": req["method"], "url": req["url"], "status": None}
            )
        else:
            xhrs.append(rec)

    return {
        "council": council,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "test_case": {
            "postcode": data.get("postcode"),
            "uprn": data.get("uprn"),
            "house_number": data.get("house_number"),
            "url": data.get("url"),
        },
        "payload": payload,
        "success": success,
        "result": result,
        "xhrs": xhrs,
        "static_assets": static_assets,
        "errors": errors,
        "duration_s": round(duration_s, 2),
        "returncode": returncode,
        "stdout_tail": stdout_tail,
        "stderr_tail": stderr_tail,
    }


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------


def _is_httpx_convertible(capture: dict) -> tuple[bool, str | None]:
    """Heuristic: does this capture look like it can be rewritten as a plain httpx call?

    Returns (guess, candidate_url). True when there's a non-static XHR whose
    body references the UPRN, postcode, or a date-ish string, and whose
    response content-type is JSON / XML / text.
    """
    uprn = (capture.get("test_case") or {}).get("uprn") or ""
    postcode = (capture.get("test_case") or {}).get("postcode") or ""
    postcode_norm = re.sub(r"\s+", "", postcode).lower()
    date_re = re.compile(r"\b(20\d{2}[-/]\d{2}[-/]\d{2}|\d{2}[-/]\d{2}[-/]20\d{2})\b")

    best: str | None = None
    for x in capture.get("xhrs", []):
        if x.get("status") is None or x["status"] >= 400:
            continue
        ct = (x.get("response_headers") or {}).get("content-type", "").lower()
        if not any(t in ct for t in ("json", "xml", "text", "html")):
            continue
        body = x.get("body") or ""
        body_lower = body.lower()
        hits = 0
        if uprn and uprn in body:
            hits += 2
        if postcode and (
            postcode.lower() in body_lower
            or postcode_norm in re.sub(r"\s+", "", body_lower)
        ):
            hits += 1
        if date_re.search(body):
            hits += 1
        if hits >= 2:
            return True, x["url"]
        if hits and best is None:
            best = x["url"]
    return False, best


def build_summary(captures: list[dict]) -> dict:
    rows = []
    for c in captures:
        httpx_ok, candidate = _is_httpx_convertible(c)
        rows.append(
            {
                "council": c["council"],
                "success": c["success"],
                "xhr_count": len(c.get("xhrs", [])),
                "static_asset_count": len(c.get("static_assets", [])),
                "httpx_convertible": httpx_ok,
                "candidate_payload_url": candidate,
                "duration_s": c.get("duration_s"),
                "errors": c.get("errors", []),
            }
        )
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total": len(rows),
        "successful": sum(1 for r in rows if r["success"]),
        "httpx_convertible": sum(1 for r in rows if r["httpx_convertible"]),
        "councils": rows,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def run(councils: list[tuple[str, dict]], parallel: int) -> list[dict]:
    CAPTURES_DIR.mkdir(parents=True, exist_ok=True)
    sem = asyncio.Semaphore(parallel)

    async def _one(name: str, data: dict) -> dict:
        try:
            capture = await asyncio.wait_for(
                capture_one(name, data, sem),
                timeout=PER_COUNCIL_TIMEOUT_S + READY_TIMEOUT_S + QUIT_TIMEOUT_S + 60,
            )
        except asyncio.TimeoutError:
            capture = {
                "council": name,
                "captured_at": datetime.now(timezone.utc).isoformat(),
                "success": False,
                "xhrs": [],
                "static_assets": [],
                "errors": ["overall timeout"],
            }
        except Exception as e:
            logger.exception("[%s] unexpected failure", name)
            capture = {
                "council": name,
                "captured_at": datetime.now(timezone.utc).isoformat(),
                "success": False,
                "xhrs": [],
                "static_assets": [],
                "errors": [f"unexpected: {e}"],
            }
        out_path = CAPTURES_DIR / f"{name}.json"
        out_path.write_text(json.dumps(capture, indent=2, default=str))
        logger.info(
            "[%s] done: success=%s xhrs=%d static=%d -> %s",
            name,
            capture.get("success"),
            len(capture.get("xhrs", [])),
            len(capture.get("static_assets", [])),
            out_path,
        )
        return capture

    return await asyncio.gather(*(_one(n, d) for n, d in councils))


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "--council",
        type=str,
        default="",
        help="Comma-separated council names (default: all eligible)",
    )
    ap.add_argument(
        "--parallel",
        type=int,
        default=MAX_PARALLEL,
        help=f"Max councils in parallel (default {MAX_PARALLEL})",
    )
    ap.add_argument(
        "--list", action="store_true", help="List eligible councils and exit"
    )
    args = ap.parse_args()

    ensure_upstream_clone()

    manifest = load_manifest()
    only = {n.strip() for n in args.council.split(",") if n.strip()} or None
    councils = eligible_councils(manifest, only)

    if args.list:
        for name, _ in councils:
            print(name)
        return

    if not councils:
        logger.warning("No eligible councils matched; nothing to do.")
        sys.exit(0)

    logger.info("Capturing %d councils with parallel=%d", len(councils), args.parallel)
    captures = asyncio.run(run(councils, parallel=max(1, args.parallel)))

    # Merge existing summary so partial runs accumulate.
    existing: dict[str, dict] = {}
    if SUMMARY_PATH.exists():
        try:
            prior = json.loads(SUMMARY_PATH.read_text())
            for row in prior.get("councils", []):
                existing[row["council"]] = row
        except Exception:
            existing = {}
    # Overlay this run's results.
    new_summary = build_summary(captures)
    for row in new_summary["councils"]:
        existing[row["council"]] = row
    merged = {
        "generated_at": new_summary["generated_at"],
        "total": len(existing),
        "successful": sum(1 for r in existing.values() if r["success"]),
        "httpx_convertible": sum(
            1 for r in existing.values() if r["httpx_convertible"]
        ),
        "councils": sorted(existing.values(), key=lambda r: r["council"]),
    }
    SUMMARY_PATH.write_text(json.dumps(merged, indent=2))
    logger.info(
        "Wrote summary: %s (successful=%d/%d, httpx_convertible=%d)",
        SUMMARY_PATH,
        merged["successful"],
        merged["total"],
        merged["httpx_convertible"],
    )


if __name__ == "__main__":
    main()
