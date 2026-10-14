"""Timeline triggers: when to run which schedule_id."""
from __future__ import annotations

import copy
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable

from session.paths import TIMELINE_PATH, assert_userdata_write, atomic_write_json, ensure_userdata
from settings.settings_sections import read_json_object

SCHEMA_VERSION = 1


@dataclass
class TimelineEntry:
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    schedule_id: str = ""
    enabled: bool = True
    time_mode: str = "window"
    start_time: str = "00:00:00"
    end_time: str = "23:59:59"
    duration_minutes: int = 90
    weekdays: list[int] = field(default_factory=lambda: list(range(7)))
    repeat_daily: bool = True

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "TimelineEntry":
        known = cls.__dataclass_fields__
        values = {k: copy.deepcopy(v) for k, v in raw.items() if k in known}
        entry = cls(**values)
        entry.id = str(entry.id or uuid.uuid4().hex)
        entry.schedule_id = str(entry.schedule_id or "").strip()
        entry.duration_minutes = max(1, min(10080, int(entry.duration_minutes or 90)))
        entry.time_mode = (
            entry.time_mode if entry.time_mode in ("window", "duration") else "window"
        )
        entry.weekdays = sorted(
            {int(day) for day in (entry.weekdays or []) if 0 <= int(day) <= 6}
        )
        if not entry.weekdays:
            entry.weekdays = list(range(7))
        return entry

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TimelineDocument:
    randomize_enabled: bool = False
    randomize_minutes: int = 0
    entries: list[TimelineEntry] = field(default_factory=list)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "TimelineDocument":
        rows = raw.get("entries", [])
        entries = [
            TimelineEntry.from_dict(row) for row in rows if isinstance(row, dict)
        ]
        return cls(
            randomize_enabled=bool(raw.get("randomize_enabled")),
            randomize_minutes=max(0, min(120, int(raw.get("randomize_minutes") or 0))),
            entries=entries,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "randomize_enabled": bool(self.randomize_enabled),
            "randomize_minutes": max(0, min(120, int(self.randomize_minutes or 0))),
            "entries": [e.to_dict() for e in self.entries],
        }

    def entry_for_schedule(self, schedule_id: str) -> TimelineEntry | None:
        sid = str(schedule_id or "").strip()
        for entry in self.entries:
            if entry.schedule_id == sid:
                return entry
        return None


def load_timeline(path=None) -> TimelineDocument:
    ensure_userdata()
    target = path or TIMELINE_PATH
    raw = read_json_object(target)
    if raw is None:
        return TimelineDocument()
    return TimelineDocument.from_dict(raw)


def save_timeline(doc: TimelineDocument, path=None) -> None:
    ensure_userdata()
    target = assert_userdata_write(path or TIMELINE_PATH)
    atomic_write_json(target, doc.to_dict())


def replace_entries_from_tasks(
    doc: TimelineDocument,
    tasks: Iterable[Any],
) -> TimelineDocument:
    """Rebuild timeline entries 1:1 from ScheduleTask-like objects (compat)."""
    entries: list[TimelineEntry] = []
    for task in tasks:
        sid = str(getattr(task, "id", "") or "").strip()
        if not sid:
            continue
        entries.append(
            TimelineEntry(
                id=uuid.uuid4().hex,
                schedule_id=sid,
                enabled=bool(getattr(task, "enabled", True)),
                time_mode=str(getattr(task, "time_mode", "window") or "window"),
                start_time=str(getattr(task, "start_time", "00:00:00") or "00:00:00"),
                end_time=str(getattr(task, "end_time", "23:59:59") or "23:59:59"),
                duration_minutes=int(getattr(task, "duration_minutes", 90) or 90),
                weekdays=list(getattr(task, "weekdays", list(range(7))) or list(range(7))),
                repeat_daily=bool(getattr(task, "repeat_daily", True)),
            )
        )
    doc.entries = entries
    return doc
