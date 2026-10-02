"""The one definition of whether a council works, shared by every consumer.

tests/test_lad_integration.py computes each LAD's status with `lad_status`
and writes it to tests/output/lad_integration_output.json.
scripts/annotate_lad_working turns that into the `working` flag in
api/data/lad_lookup.json; generate_sankey, the badge and the coverage map
read the flag back rather than re-deriving it.

The rule:
  working     a *sampled* case passed (200 + at least one date). Sampled
              cases carry exactly what the frontend sends, so this is "a real
              user can get a schedule". For LADs the frontend cannot drive
              (`fixture_only`: the scraper requires params such as property_id
              or usrn that /find doesn't return), a fixture pass counts
              instead.
  broken      anything else that was actually tested. A fixture pass with every
              sampled case failing is broken: the scraper runs, users can't
              reach it.
  deeplink    no deciding case passed and the scraper answered with a deeplink
              (it raised NeedsBrowser: captcha, login) where it answered at all.
              Users are sent to the council's page; not `working`.
  unverified  every case was unreachable from the test machine, or there was
              no case able to decide (no sampled address found). The previous
              `working` flag is kept.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LAD_OUTPUT_PATH = ROOT / "tests" / "output" / "lad_integration_output.json"


def deciding_cases(cases: list[dict], fixture_only: bool) -> list[dict]:
    """The cases whose outcome decides the LAD's status."""
    return [c for c in cases if c["source"] == ("fixture" if fixture_only else "sampled")]


def lad_status(cases: list[dict], fixture_only: bool) -> tuple[str, str | None]:
    """(status, reason) for one LAD's run cases, each with source + outcome."""
    deciding = deciding_cases(cases, fixture_only)
    if any(c["outcome"] == "pass" for c in deciding):
        return "working", None
    if not deciding:
        return "unverified", "no sampled case" if not fixture_only else "no fixture case"
    if all(c["outcome"] == "unreachable" for c in deciding):
        return "unverified", "unreachable"
    if all(c["outcome"] in {"deeplink", "unreachable"} for c in deciding):
        return "deeplink", next(c.get("error") for c in deciding if c["outcome"] == "deeplink") or None
    outcomes = sorted({c["outcome"] for c in deciding} - {"unreachable"})
    if not fixture_only and any(c["source"] == "fixture" and c["outcome"] == "pass" for c in cases):
        return "broken", "fixture passes, sampled fails: " + ",".join(outcomes)
    return "broken", ",".join(outcomes)


def _load_lads() -> dict[str, dict]:
    if not LAD_OUTPUT_PATH.exists():
        return {}
    return json.loads(LAD_OUTPUT_PATH.read_text()).get("lads", {})


def working_by_lad(lad_lookup: dict) -> dict[str, bool]:
    """LAD code -> working, for every LAD in lad_lookup."""
    lads = _load_lads()
    out = {}
    for code, info in lad_lookup.items():
        previous = bool(info.get("working"))
        if not info.get("scraper_id"):
            out[code] = False
            continue
        r = lads.get(code)
        # Not in this run, or tested against a different module: keep the flag
        if r is None or r.get("scraper_id") != info["scraper_id"] or r["status"] == "unverified":
            out[code] = previous
        else:
            out[code] = r["status"] == "working"
    return out


def pass_rate_by_lad() -> dict[str, float]:
    """LAD code -> share of deciding cases that passed in the last run."""
    rates = {}
    for code, r in _load_lads().items():
        deciding = deciding_cases(r["cases"], r.get("fixture_only", False))
        if deciding:
            rates[code] = sum(c["outcome"] == "pass" for c in deciding) / len(deciding)
    return rates
