from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from weakref import WeakValueDictionary

from icalendar import Calendar, Event

from api import config
from api.councils._base import Collection

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CacheEntry:
    uprn: str
    scraper: str
    params: dict[str, str]
    ics_path: Path
    sidecar_path: Path
    last_scraped: datetime | None
    last_success: datetime | None
    last_error: str | None
    next_collection: date | None
    collections: list[dict]
    consecutive_failures: int


def _stable_uid(uprn: str, date_iso: str, type_: str) -> str:
    digest = hashlib.sha1(f"{uprn}|{date_iso}|{type_}".encode()).hexdigest()
    return f"{digest}@bins.local"


def _iso_utc(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _collection_dicts(collections: list[Collection], uprn: str) -> list[dict]:
    out: list[dict] = []
    for c in collections:
        d = c.date.isoformat() if isinstance(c.date, date) else str(c.date)
        item = {
            "date": d,
            "type": c.type,
            "icon": c.icon,
            "uid": _stable_uid(uprn, d, c.type),
        }
        out.append(item)
    return out


class IcsCache:
    """Disk-backed ICS cache keyed by UPRN."""

    def __init__(self, root: Path, canonical_id: Callable[[str], str] | None = None) -> None:
        """`canonical_id` resolves an old council ID to its public one (the
        registry's), so a sidecar written under an old scraper ID still counts
        as the same council as its LAD code."""
        self.root = Path(root)
        self._canonical_id = canonical_id or (lambda scraper_id: scraper_id)
        self.root.mkdir(parents=True, exist_ok=True)
        self._locks: WeakValueDictionary[str, asyncio.Lock] = WeakValueDictionary()

    def _lock_for(self, uprn: str) -> asyncio.Lock:
        lock = self._locks.get(uprn)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[uprn] = lock
        return lock

    def paths_for(self, uprn: str) -> tuple[Path, Path]:
        return (self.root / f"{uprn}.ics", self.root / f"{uprn}.json")

    def _build_entry(self, sidecar: dict) -> CacheEntry:
        uprn = sidecar["uprn"]
        ics_path, sidecar_path = self.paths_for(uprn)
        return CacheEntry(
            uprn=uprn,
            scraper=sidecar.get("scraper", ""),
            params=sidecar.get("params", {}),
            ics_path=ics_path,
            sidecar_path=sidecar_path,
            last_scraped=_parse_iso(sidecar.get("last_scraped")),
            last_success=_parse_iso(sidecar.get("last_success")),
            last_error=sidecar.get("last_error"),
            next_collection=_parse_date(sidecar.get("next_collection")),
            collections=sidecar.get("collections", []),
            consecutive_failures=int(sidecar.get("consecutive_failures", 0)),
        )

    async def read(self, uprn: str) -> CacheEntry | None:
        return await asyncio.to_thread(self._read_sync, uprn)

    def _read_sync(self, uprn: str) -> CacheEntry | None:
        ics_path, sidecar_path = self.paths_for(uprn)
        if not ics_path.exists() or not sidecar_path.exists():
            return None
        try:
            data = json.loads(sidecar_path.read_text())
        except (OSError, json.JSONDecodeError):
            logger.warning("Failed to read sidecar %s", sidecar_path, exc_info=True)
            return None
        return self._build_entry(data)

    async def read_ics_bytes(self, uprn: str) -> bytes | None:
        return await asyncio.to_thread(self._read_ics_bytes_sync, uprn)

    def _read_ics_bytes_sync(self, uprn: str) -> bytes | None:
        ics_path, _ = self.paths_for(uprn)
        if not ics_path.exists():
            return None
        try:
            return ics_path.read_bytes()
        except OSError:
            return None

    def _load_ics(self, ics_path: Path) -> Calendar:
        if ics_path.exists():
            try:
                return Calendar.from_ical(ics_path.read_bytes())
            except (ValueError, OSError):
                logger.warning("Failed to parse existing ICS %s — rebuilding", ics_path)
        cal = Calendar()
        cal.add("prodid", "-//UK Bin Collections//bins//EN")
        cal.add("version", "2.0")
        return cal

    def _atomic_write(self, path: Path, content: bytes) -> None:
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_bytes(content)
        os.replace(tmp, path)

    def _split_components(
        self, cal: Calendar
    ) -> tuple[dict[str, Event], list]:
        events_by_uid: dict[str, Event] = {}
        other_components: list = []
        for comp in cal.subcomponents:
            if comp.name == "VEVENT":
                uid = str(comp.get("UID", ""))
                if uid:
                    events_by_uid[uid] = comp
            else:
                other_components.append(comp)
        return events_by_uid, other_components

    def _refresh_existing(
        self,
        events_by_uid: dict[str, Event],
        cutoff: date,
        now: datetime,
    ) -> dict[str, Event]:
        merged: dict[str, Event] = {}
        for uid, ev in events_by_uid.items():
            dtstart = ev.get("DTSTART")
            if dtstart is None:
                continue
            d = dtstart.dt
            if isinstance(d, datetime):
                d = d.date()
            if d < cutoff:
                continue
            if "DTSTAMP" in ev:
                del ev["DTSTAMP"]
            ev.add("dtstamp", now)
            merged[uid] = ev
        return merged

    def _merge_new(
        self,
        merged: dict[str, Event],
        new_collections: list[dict],
        cutoff: date,
        now: datetime,
    ) -> None:
        for c in new_collections:
            uid = c["uid"]
            if uid in merged:
                continue
            d = date.fromisoformat(c["date"])
            if d < cutoff:
                continue
            ev = Event()
            ev.add("summary", c["type"])
            ev.add("dtstart", d)
            ev.add("dtend", d + timedelta(days=1))
            ev.add("uid", uid)
            ev.add("dtstamp", now)
            if c.get("icon"):
                ev.add("description", c["icon"])
            merged[uid] = ev

    def _build_calendar(
        self,
        uprn: str,
        merged: dict[str, Event],
        other_components: list,
        now: datetime,
    ) -> Calendar:
        new_cal = Calendar()
        new_cal.add("prodid", "-//UK Bin Collections//bins//EN")
        new_cal.add("version", "2.0")
        new_cal.add("x-wr-calname", f"Bin Collections ({uprn})")
        new_cal.add("last-modified", now)
        for comp in other_components:
            new_cal.add_component(comp)
        for ev in sorted(merged.values(), key=lambda e: e.get("DTSTART").dt):
            new_cal.add_component(ev)
        return new_cal

    def _merge_and_prune(
        self,
        ics_path: Path,
        uprn: str,
        new_collections: list[dict],
        retention_days: int,
        today: date,
    ) -> Calendar:
        cal = self._load_ics(ics_path)
        events_by_uid, other_components = self._split_components(cal)

        now = datetime.now(UTC)
        cutoff = today - timedelta(days=retention_days)

        merged = self._refresh_existing(events_by_uid, cutoff, now)
        self._merge_new(merged, new_collections, cutoff, now)
        return self._build_calendar(uprn, merged, other_components, now)

    def _extract_upcoming(self, cal: Calendar, uprn: str, today: date) -> list[dict]:
        items: list[dict] = []
        for comp in cal.subcomponents:
            if comp.name != "VEVENT":
                continue
            dtstart = comp.get("DTSTART")
            if dtstart is None:
                continue
            d = dtstart.dt
            if isinstance(d, datetime):
                d = d.date()
            if d < today:
                continue
            summary = str(comp.get("SUMMARY", ""))
            description = comp.get("DESCRIPTION")
            icon = str(description) if description else None
            date_iso = d.isoformat()
            items.append(
                {
                    "date": date_iso,
                    "type": summary,
                    "icon": icon,
                    "uid": str(comp.get("UID", _stable_uid(uprn, date_iso, summary))),
                }
            )
        items.sort(key=lambda x: x["date"])
        return items[: config.ICS_SIDECAR_UPCOMING_LIMIT]

    async def write(
        self,
        uprn: str,
        scraper_id: str,
        params: dict[str, str],
        collections: list[Collection],
    ) -> CacheEntry:
        async with self._lock_for(uprn):
            return await asyncio.to_thread(
                self._write_sync, uprn, scraper_id, params, collections
            )

    def _write_sync(
        self,
        uprn: str,
        scraper_id: str,
        params: dict[str, str],
        collections: list[Collection],
    ) -> CacheEntry:
        ics_path, sidecar_path = self.paths_for(uprn)
        today = date.today()
        new_dicts = _collection_dicts(collections, uprn)

        existing: dict = {}
        if sidecar_path.exists():
            try:
                existing = json.loads(sidecar_path.read_text())
            except (OSError, json.JSONDecodeError):
                existing = {}
        # Events from a different scraper are a different council's data;
        # start the calendar afresh rather than merging them in.
        if existing.get("scraper") and self._canonical_id(existing["scraper"]) != self._canonical_id(scraper_id):
            ics_path.unlink(missing_ok=True)
            existing = {}

        cal = self._merge_and_prune(
            ics_path, uprn, new_dicts, config.ICS_RETENTION_DAYS, today
        )
        self._atomic_write(ics_path, cal.to_ical())

        upcoming = self._extract_upcoming(cal, uprn, today)
        next_collection = upcoming[0]["date"] if upcoming else None

        now = datetime.now(UTC)

        sidecar = {
            "uprn": uprn,
            "scraper": scraper_id,
            "params": params,
            "created_at": existing.get("created_at") or _iso_utc(now),
            "last_scraped": _iso_utc(now),
            "last_success": _iso_utc(now),
            "last_error": None,
            "consecutive_failures": 0,
            "next_collection": next_collection,
            "collections": upcoming,
        }
        self._atomic_write(
            sidecar_path,
            json.dumps(sidecar, indent=2, default=str).encode(),
        )
        return self._build_entry(sidecar)

    async def record_failure(
        self,
        uprn: str,
        error: str,
        *,
        scraper_id: str = "",
        params: dict[str, str] | None = None,
    ) -> None:
        async with self._lock_for(uprn):
            await asyncio.to_thread(
                self._record_failure_sync, uprn, error, scraper_id, params or {}
            )

    def _record_failure_sync(
        self,
        uprn: str,
        error: str,
        scraper_id: str,
        params: dict[str, str],
    ) -> None:
        _, sidecar_path = self.paths_for(uprn)
        now_iso = _iso_utc(datetime.now(UTC))
        data: dict = {}
        if sidecar_path.exists():
            try:
                data = json.loads(sidecar_path.read_text())
            except (OSError, json.JSONDecodeError):
                data = {}
        if not data:
            data = {
                "uprn": uprn,
                "scraper": scraper_id,
                "params": params,
                "created_at": now_iso,
                "last_success": None,
                "next_collection": None,
                "collections": [],
            }
        data["last_scraped"] = now_iso
        data["last_error"] = error[:500]
        data["consecutive_failures"] = int(data.get("consecutive_failures", 0)) + 1
        self._atomic_write(
            sidecar_path,
            json.dumps(data, indent=2, default=str).encode(),
        )

    def iter_entries(self) -> Iterator[CacheEntry]:
        for sidecar_path in sorted(self.root.glob("*.json")):
            try:
                data = json.loads(sidecar_path.read_text())
            except (OSError, json.JSONDecodeError):
                continue
            if "uprn" not in data:
                continue
            yield self._build_entry(data)

    async def delete(self, uprn: str) -> None:
        async with self._lock_for(uprn):
            await asyncio.to_thread(self._delete_sync, uprn)

    def _delete_sync(self, uprn: str) -> None:
        ics_path, sidecar_path = self.paths_for(uprn)
        for p in (ics_path, sidecar_path):
            try:
                p.unlink()
            except FileNotFoundError:
                pass

    def count_entries(self) -> int:
        return sum(1 for _ in self.root.glob("*.json"))
