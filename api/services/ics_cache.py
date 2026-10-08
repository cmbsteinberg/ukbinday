from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from weakref import WeakValueDictionary

from icalendar import Calendar, Event

from api import config
from api.councils._base import Collection, colour_of
from api.services.blob_store import BlobStore

logger = logging.getLogger(__name__)

HEARTBEAT_KEY = "meta/refresh_heartbeat.json"


@dataclass(frozen=True)
class CacheEntry:
    uprn: str
    scraper: str
    params: dict[str, str]
    last_scraped: datetime | None
    last_success: datetime | None
    last_error: str | None
    next_collection: date | None
    collections: list[dict]
    consecutive_failures: int


# Bin colour -> (RFC 7986 COLOR, a CSS name; emoji prefixed to SUMMARY, where
# Unicode has a matching circle). Most apps ignore COLOR, so the emoji is what
# Google/Apple/Outlook subscribers actually see.
_EVENT_COLOURS: dict[str, tuple[str, str | None]] = {
    "Black": ("black", "\u26ab"),
    "Blue": ("blue", "\U0001f535"),
    "Brown": ("brown", "\U0001f7e4"),
    "Green": ("green", "\U0001f7e2"),
    "Grey": ("grey", None),
    "Purple": ("purple", "\U0001f7e3"),
    "Red": ("red", "\U0001f534"),
    "White": ("white", "\u26aa"),
    "Yellow": ("yellow", "\U0001f7e1"),
    "Orange": ("orange", "\U0001f7e0"),
    "Pink": ("pink", None),
    "Burgundy": ("maroon", None),
}
_EMOJI_PREFIXES = tuple(f"{e} " for _, e in _EVENT_COLOURS.values() if e)


def _strip_emoji(summary: str) -> str:
    for prefix in _EMOJI_PREFIXES:
        if summary.startswith(prefix):
            return summary[len(prefix) :]
    return summary


def _set_label(ev: Event, type_: str) -> None:
    """SUMMARY (emoji-prefixed when the label names a bin colour) and COLOR."""
    for key in ("SUMMARY", "COLOR"):
        if key in ev:
            del ev[key]
    css, emoji = _EVENT_COLOURS.get(colour_of(type_) or "", (None, None))
    ev.add("summary", f"{emoji} {type_}" if emoji else type_)
    if css:
        ev.add("color", css)


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


def _shard_of(uprn: str, of: int) -> int:
    """Which of `of` refresh shards owns this UPRN. A non-numeric one (never
    cached by the routes) goes to shard 0 rather than belonging to none."""
    return int(uprn) % of if uprn.isascii() and uprn.isdigit() else 0


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
    """ICS cache keyed by UPRN, over a blob store: `calendars/{uprn}.ics` is the
    calendar, `calendars/{uprn}.json` its sidecar."""

    def __init__(self, store: BlobStore, canonical_id: Callable[[str], str] | None = None) -> None:
        """`canonical_id` resolves an old council ID to its public one (the
        registry's), so a sidecar written under an old scraper ID still counts
        as the same council as its LAD code."""
        self.store = store
        self._canonical_id = canonical_id or (lambda scraper_id: scraper_id)
        self._locks: WeakValueDictionary[str, asyncio.Lock] = WeakValueDictionary()

    def _lock_for(self, uprn: str) -> asyncio.Lock:
        lock = self._locks.get(uprn)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[uprn] = lock
        return lock

    def keys_for(self, uprn: str) -> tuple[str, str]:
        """The (ics, sidecar) keys."""
        return (
            f"{config.ICS_CACHE_SUBDIR}/{uprn}.ics",
            f"{config.ICS_CACHE_SUBDIR}/{uprn}.json",
        )

    def _read_sidecar_data(self, sidecar_key: str) -> dict | None:
        raw = self.store.get(sidecar_key)
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("Failed to read sidecar %s", sidecar_key, exc_info=True)
            return None

    def _build_entry(self, sidecar: dict) -> CacheEntry:
        uprn = sidecar["uprn"]
        return CacheEntry(
            uprn=uprn,
            scraper=sidecar.get("scraper", ""),
            params=sidecar.get("params", {}),
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
        ics_key, sidecar_key = self.keys_for(uprn)
        data = self._read_sidecar_data(sidecar_key)
        if data is None or self.store.get(ics_key) is None:
            return None
        return self._build_entry(data)

    async def read_ics_bytes(self, uprn: str) -> bytes | None:
        return await asyncio.to_thread(self._read_ics_bytes_sync, uprn)

    def _read_ics_bytes_sync(self, uprn: str) -> bytes | None:
        ics_key, _ = self.keys_for(uprn)
        return self.store.get(ics_key)

    def _load_ics(self, raw: bytes | None, ics_key: str) -> Calendar:
        if raw is not None:
            try:
                return Calendar.from_ical(raw)
            except ValueError:
                logger.warning("Failed to parse existing ICS %s — rebuilding", ics_key)
        cal = Calendar()
        cal.add("prodid", "-//UK Bin Collections//bins//EN")
        cal.add("version", "2.0")
        return cal

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
            _set_label(ev, _strip_emoji(str(ev.get("SUMMARY", ""))))
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
            _set_label(ev, c["type"])
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
        raw_ics: bytes | None,
        ics_key: str,
        uprn: str,
        new_collections: list[dict],
        retention_days: int,
        today: date,
    ) -> Calendar:
        cal = self._load_ics(raw_ics, ics_key)
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
            summary = _strip_emoji(str(comp.get("SUMMARY", "")))
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
        ics_key, sidecar_key = self.keys_for(uprn)
        today = date.today()
        new_dicts = _collection_dicts(collections, uprn)

        existing = self._read_sidecar_data(sidecar_key) or {}
        raw_ics = self.store.get(ics_key)
        # Events from a different scraper are a different council's data;
        # start the calendar afresh rather than merging them in.
        if existing.get("scraper") and self._canonical_id(existing["scraper"]) != self._canonical_id(scraper_id):
            raw_ics = None
            existing = {}

        cal = self._merge_and_prune(
            raw_ics, ics_key, uprn, new_dicts, config.ICS_RETENTION_DAYS, today
        )
        # ICS first, sidecar last: a sidecar never points at a missing calendar
        self.store.put(ics_key, cal.to_ical())
        sidecar = self._sidecar(uprn, scraper_id, params, cal, existing, today)
        self.store.put(sidecar_key, json.dumps(sidecar, indent=2, default=str).encode())
        return self._build_entry(sidecar)

    def unsaved_entry(
        self,
        uprn: str,
        scraper_id: str,
        params: dict[str, str],
        collections: list[Collection],
    ) -> CacheEntry:
        """The entry `write` would return, without touching the store: what a
        scrape answers with when the store is down."""
        today = date.today()
        cal = self._merge_and_prune(
            None, "", uprn, _collection_dicts(collections, uprn), config.ICS_RETENTION_DAYS, today
        )
        return self._build_entry(self._sidecar(uprn, scraper_id, params, cal, {}, today))

    def _sidecar(
        self,
        uprn: str,
        scraper_id: str,
        params: dict[str, str],
        cal: Calendar,
        existing: dict,
        today: date,
    ) -> dict:
        upcoming = self._extract_upcoming(cal, uprn, today)
        next_collection = upcoming[0]["date"] if upcoming else None

        now = datetime.now(UTC)

        return {
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
        _, sidecar_key = self.keys_for(uprn)
        now_iso = _iso_utc(datetime.now(UTC))
        data = self._read_sidecar_data(sidecar_key) or {}
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
        self.store.put(sidecar_key, json.dumps(data, indent=2, default=str).encode())

    async def sidecar_uprns(self, shard: int = 0, of: int = 1) -> list[str]:
        """UPRNs with a sidecar that belong to refresh shard `shard` of `of`."""
        return await asyncio.to_thread(self._sidecar_uprns_sync, shard, of)

    def _sidecar_uprns_sync(self, shard: int, of: int) -> list[str]:
        prefix = f"{config.ICS_CACHE_SUBDIR}/"
        uprns = (
            key.removeprefix(prefix).removesuffix(".json")
            for key in self.store.keys(prefix)
            if key.endswith(".json")
        )
        return [u for u in uprns if _shard_of(u, of) == shard]

    async def read_sidecar(self, uprn: str) -> CacheEntry | None:
        """Like `read`, but also returns an entry that has no calendar (a UPRN
        whose first scrape failed), which the refresh still has to retry."""
        return await asyncio.to_thread(self._read_sidecar_sync, uprn)

    def _read_sidecar_sync(self, uprn: str) -> CacheEntry | None:
        data = self._read_sidecar_data(self.keys_for(uprn)[1])
        if data is None or "uprn" not in data:
            return None
        return self._build_entry(data)

    async def delete(self, uprn: str) -> None:
        async with self._lock_for(uprn):
            await asyncio.to_thread(self._delete_sync, uprn)

    def _delete_sync(self, uprn: str) -> None:
        for key in self.keys_for(uprn):
            self.store.delete(key)

    async def read_heartbeat(self) -> dict | None:
        """The refresh heartbeat: `{"of": n, "shards": {"<i>": {"last_run",
        "entries", "stats"}}}`, one record per shard of the current shard count."""
        return await asyncio.to_thread(self._read_heartbeat_sync)

    def _read_heartbeat_sync(self) -> dict | None:
        raw = self.store.get(HEARTBEAT_KEY)
        legacy = None
        if raw is not None:
            try:
                legacy = json.loads(raw)
            except json.JSONDecodeError:
                pass
        records = []
        for key in self.store.keys("meta/refresh_shards/"):
            raw = self.store.get(key)
            if raw is not None:
                try:
                    records.append(json.loads(raw))
                except json.JSONDecodeError:
                    continue
        if not records:
            return legacy
        # The most recently completed pass selects the active layout. Each
        # shard owns its file, so overlapping instances cannot lose updates.
        latest = max(records, key=lambda record: record["last_run"])
        of = latest["of"]
        return {
            "of": of,
            "shards": {
                str(record["shard"]): {
                    key: record[key] for key in ("last_run", "entries", "stats")
                }
                for record in records if record["of"] == of
            },
        }

    async def write_heartbeat(self, shard: int, of: int, entries: int, stats: dict) -> None:
        """Record a finished pass of one shard, keeping the other shards' records
        (dropped when the shard count changed, so a retired layout can't look stale)."""
        await asyncio.to_thread(self._write_heartbeat_sync, shard, of, entries, stats)

    def _write_heartbeat_sync(self, shard: int, of: int, entries: int, stats: dict) -> None:
        record = {
            "of": of,
            "shard": shard,
            "last_run": _iso_utc(datetime.now(UTC)),
            "entries": entries,
            "stats": stats,
        }
        key = f"meta/refresh_shards/{of}/{shard}.json"
        self.store.put(key, json.dumps(record).encode())
