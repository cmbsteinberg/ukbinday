"""
Profile Playwright test suite: wall time, peak memory (Python + Chromium children).

Usage:
    uv run python tests/profile_playwright.py

Reports:
  - Wall clock time for the full test batch
  - Memory snapshots at key points (before browser, after pool start, during tests, after cleanup)
  - Peak RSS across the entire process tree (Python + Chromium subprocesses)
  - Per-test timing breakdown
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path

import psutil

# ---------------------------------------------------------------------------
# Memory helpers
# ---------------------------------------------------------------------------

def get_process_tree_memory_mb() -> dict:
    """Get memory usage of current process + all children (Chromium, etc.)."""
    proc = psutil.Process(os.getpid())
    children = proc.children(recursive=True)

    python_rss = proc.memory_info().rss / (1024 * 1024)
    child_details = []
    child_total = 0.0

    for child in children:
        try:
            info = child.memory_info()
            child_rss = info.rss / (1024 * 1024)
            child_total += child_rss
            child_details.append({
                "pid": child.pid,
                "name": child.name(),
                "rss_mb": round(child_rss, 1),
            })
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    return {
        "python_rss_mb": round(python_rss, 1),
        "children_rss_mb": round(child_total, 1),
        "total_rss_mb": round(python_rss + child_total, 1),
        "child_count": len(children),
        "children": sorted(child_details, key=lambda x: -x["rss_mb"])[:10],
    }


class MemoryTracker:
    """Track peak memory across the process tree by polling."""

    def __init__(self, interval: float = 0.5):
        self.interval = interval
        self.peak_total_mb = 0.0
        self.peak_snapshot: dict = {}
        self.snapshots: list[dict] = []
        self._task: asyncio.Task | None = None

    async def start(self):
        self._task = asyncio.create_task(self._poll())

    async def stop(self):
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _poll(self):
        while True:
            snap = get_process_tree_memory_mb()
            snap["timestamp"] = time.monotonic()
            self.snapshots.append(snap)
            if snap["total_rss_mb"] > self.peak_total_mb:
                self.peak_total_mb = snap["total_rss_mb"]
                self.peak_snapshot = snap
            await asyncio.sleep(self.interval)

    def snapshot(self, label: str) -> dict:
        snap = get_process_tree_memory_mb()
        snap["label"] = label
        snap["timestamp"] = time.monotonic()
        self.snapshots.append(snap)
        if snap["total_rss_mb"] > self.peak_total_mb:
            self.peak_total_mb = snap["total_rss_mb"]
            self.peak_snapshot = snap
        return snap


# ---------------------------------------------------------------------------
# Test runner
# ---------------------------------------------------------------------------

async def run_profile():
    tracker = MemoryTracker(interval=0.5)

    # --- Baseline ---
    baseline = tracker.snapshot("baseline (before imports)")
    print(f"\n{'='*70}")
    print("PLAYWRIGHT PROFILER")
    print(f"{'='*70}")
    print(f"Baseline memory: {baseline['total_rss_mb']} MB "
          f"(Python: {baseline['python_rss_mb']} MB)")

    # --- Import app ---
    t0 = time.monotonic()
    import httpx
    from asgi_lifespan import LifespanManager

    from api.main import app

    after_import = tracker.snapshot("after app import")
    print(f"After import:    {after_import['total_rss_mb']} MB "
          f"(+{after_import['total_rss_mb'] - baseline['total_rss_mb']:.1f} MB)")

    # --- Start app (triggers BrowserPool.start) ---
    print("\nStarting app (BrowserPool + registry)...")
    t_start = time.monotonic()
    manager = LifespanManager(app)
    await manager.__aenter__()
    t_lifespan = time.monotonic() - t_start

    after_start = tracker.snapshot("after lifespan start (browser launched)")
    print(f"After startup:   {after_start['total_rss_mb']} MB "
          f"(+{after_start['total_rss_mb'] - after_import['total_rss_mb']:.1f} MB) "
          f"[{t_lifespan:.1f}s]")
    print(f"  Children: {after_start['child_count']} processes")
    for child in after_start.get("children", [])[:5]:
        print(f"    PID {child['pid']} {child['name']}: {child['rss_mb']} MB")

    # --- Load test cases ---
    test_cases_path = Path(__file__).parent / "test_cases.json"
    scrapers_dir = Path(__file__).resolve().parent.parent / "api" / "scrapers"
    data = json.loads(test_cases_path.read_text())

    pw_ids = set()
    for p in scrapers_dir.glob("*.py"):
        try:
            source = p.read_text()
        except OSError:
            continue
        if "_get_browser_pool" in source or "async_playwright" in source:
            pw_ids.add(p.stem)

    cases = []
    for council, entries in sorted(data.items()):
        if council not in pw_ids:
            continue
        for entry in entries:
            cases.append((council, entry["label"], entry["params"]))

    print(f"\nFound {len(cases)} Playwright test cases across {len(pw_ids)} scrapers")

    if not cases:
        print("No test cases found — exiting.")
        await manager.__aexit__(None, None, None)
        return

    # --- Run tests ---
    await tracker.start()

    transport = httpx.ASGITransport(app=manager.app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver/api/v1", timeout=120
    ) as client:
        semaphore = asyncio.Semaphore(10)
        results = []

        async def run_one(council, label, params):
            params = dict(params)
            uprn = str(params.pop("uprn", "0"))
            query = {"council": council, **params}
            async with semaphore:
                t_req = time.monotonic()
                try:
                    resp = await client.get(f"/lookup/{uprn}", params=query)
                    elapsed = time.monotonic() - t_req
                    ok = resp.status_code == 200
                    body = resp.json() if ok else {}
                    n_collections = len(body.get("collections", []))
                    return {
                        "council": council,
                        "label": label,
                        "elapsed_s": round(elapsed, 2),
                        "status": resp.status_code,
                        "collections": n_collections,
                        "passed": ok and n_collections > 0,
                    }
                except Exception as e:
                    elapsed = time.monotonic() - t_req
                    return {
                        "council": council,
                        "label": label,
                        "elapsed_s": round(elapsed, 2),
                        "error": f"{type(e).__name__}: {e}",
                        "passed": False,
                    }

        print(f"\nRunning {len(cases)} tests (concurrency=10)...")
        t_tests = time.monotonic()
        results = await asyncio.gather(
            *[run_one(c, label, p) for c, label, p in cases]
        )
        t_tests_elapsed = time.monotonic() - t_tests

    during_tests = tracker.snapshot("after all tests complete")

    await tracker.stop()

    # --- Shutdown ---
    t_shutdown = time.monotonic()
    await manager.__aexit__(None, None, None)
    t_shutdown_elapsed = time.monotonic() - t_shutdown
    after_shutdown = tracker.snapshot("after shutdown")

    total_elapsed = time.monotonic() - t0

    # --- Report ---
    passed = [r for r in results if r["passed"]]
    failed = [r for r in results if not r["passed"]]
    timings = sorted([r["elapsed_s"] for r in results])

    print(f"\n{'='*70}")
    print("RESULTS")
    print(f"{'='*70}")
    print(f"Passed:          {len(passed)}/{len(results)}")
    print(f"Failed:          {len(failed)}/{len(results)}")

    print("\n--- Timing ---")
    print(f"Startup:         {t_lifespan:.1f}s")
    print(f"Test batch:      {t_tests_elapsed:.1f}s")
    print(f"Shutdown:        {t_shutdown_elapsed:.1f}s")
    print(f"Total:           {total_elapsed:.1f}s")
    if timings:
        print(f"Per-test min:    {timings[0]:.1f}s")
        print(f"Per-test median: {timings[len(timings)//2]:.1f}s")
        print(f"Per-test p95:    {timings[int(len(timings)*0.95)]:.1f}s")
        print(f"Per-test max:    {timings[-1]:.1f}s")
        print(f"Per-test mean:   {sum(timings)/len(timings):.1f}s")

    print("\n--- Memory ---")
    print(f"Baseline:        {baseline['total_rss_mb']} MB")
    print(f"After startup:   {after_start['total_rss_mb']} MB "
          f"(browser: +{after_start['total_rss_mb'] - after_import['total_rss_mb']:.0f} MB)")
    print(f"During tests:    {during_tests['total_rss_mb']} MB")
    print(f"Peak (polled):   {tracker.peak_total_mb:.0f} MB")
    print(f"After shutdown:  {after_shutdown['total_rss_mb']} MB")
    print(f"Peak children:   {tracker.peak_snapshot.get('child_count', '?')} processes")
    if tracker.peak_snapshot.get("children"):
        print("Peak breakdown:")
        print(f"  Python:        {tracker.peak_snapshot['python_rss_mb']} MB")
        for child in tracker.peak_snapshot.get("children", [])[:8]:
            print(f"  {child['name']:20s} PID {child['pid']:6d}: {child['rss_mb']:>7.1f} MB")

    # Per-test details
    if failed:
        print("\n--- Failed tests ---")
        for r in sorted(failed, key=lambda x: x["council"]):
            err = r.get("error", f"HTTP {r.get('status', '?')}")
            print(f"  {r['council']}: {err} ({r['elapsed_s']}s)")

    print("\n--- Slowest 10 tests ---")
    for r in sorted(results, key=lambda x: -x["elapsed_s"])[:10]:
        status = "OK" if r["passed"] else "FAIL"
        print(f"  {r['elapsed_s']:6.1f}s  [{status}]  {r['council']}")

    # Write JSON report
    report = {
        "timing": {
            "startup_s": round(t_lifespan, 2),
            "test_batch_s": round(t_tests_elapsed, 2),
            "shutdown_s": round(t_shutdown_elapsed, 2),
            "total_s": round(total_elapsed, 2),
            "per_test_min_s": timings[0] if timings else None,
            "per_test_median_s": timings[len(timings)//2] if timings else None,
            "per_test_p95_s": timings[int(len(timings)*0.95)] if timings else None,
            "per_test_max_s": timings[-1] if timings else None,
        },
        "memory": {
            "baseline_mb": baseline["total_rss_mb"],
            "after_startup_mb": after_start["total_rss_mb"],
            "during_tests_mb": during_tests["total_rss_mb"],
            "peak_mb": round(tracker.peak_total_mb, 1),
            "after_shutdown_mb": after_shutdown["total_rss_mb"],
            "peak_children_count": tracker.peak_snapshot.get("child_count"),
            "peak_snapshot": tracker.peak_snapshot,
        },
        "results_summary": {
            "total": len(results),
            "passed": len(passed),
            "failed": len(failed),
        },
        "results": results,
    }
    report_path = Path(__file__).parent / "playwright_profile.json"
    report_path.write_text(json.dumps(report, indent=2, default=str) + "\n")
    print(f"\nFull report: {report_path}")


if __name__ == "__main__":
    asyncio.run(run_profile())
