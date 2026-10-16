"""UI routine cursor: schedule → account → move.routine[].

Routine rows should already be normalized by session/settings before
``init_routine_on_blackboard``. ``from_routine`` keeps a local fallback
normalizer for unit tests without settings.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

from . import pack_ids
from . import planner_api as api
from .overlays import farm_rects_selected, patrol_entries, safe_rects_selected

MAX_ROUTINE_MINUTES = 24 * 60


def _normalize_routine_fallback(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        map_id = str(item.get("map_id") or "").strip()
        if not map_id:
            continue
        kind = str(item.get("kind") or "battle").strip().lower()
        if kind not in ("battle", "break"):
            kind = "battle"
        try:
            minutes = int(item.get("duration_minutes", 60))
        except (TypeError, ValueError):
            minutes = 60
        minutes = max(1, min(MAX_ROUTINE_MINUTES, minutes))
        entry_id = str(item.get("id") or "").strip() or uuid.uuid4().hex
        if entry_id in seen:
            entry_id = uuid.uuid4().hex
        seen.add(entry_id)
        farms: list[str] = []
        for name in item.get("selected_farms") or []:
            text = str(name).strip()
            if text and text not in farms:
                farms.append(text)
        stays_raw = item.get("farm_stays_s") or {}
        stays: dict[str, float] = {}
        if isinstance(stays_raw, dict):
            for k, v in stays_raw.items():
                try:
                    stays[str(k)] = float(v)
                except (TypeError, ValueError):
                    continue
        out.append(
            {
                "id": entry_id,
                "map_id": map_id,
                "kind": kind,
                "duration_minutes": minutes,
                "selected_farms": farms,
                "farm_stays_s": {n: stays[n] for n in farms if n in stays},
            }
        )
    return out


@dataclass
class RoutineCursor:
    entries: list[dict[str, Any]] = field(default_factory=list)
    index: int = 0
    started_at: float = 0.0
    fail_mask: set[int] = field(default_factory=set)
    cycle_start_index: int = 0

    @classmethod
    def from_entries(cls, entries: list[dict[str, Any]] | None) -> "RoutineCursor":
        """Build from already-normalized routine rows (session inject path)."""
        rows = [dict(e) for e in (entries or []) if isinstance(e, dict)]
        return cls(entries=rows, index=0, started_at=time.monotonic())

    @classmethod
    def from_routine(cls, raw: Any) -> "RoutineCursor":
        """Local normalize fallback (tests / missing session inject)."""
        return cls.from_entries(_normalize_routine_fallback(raw))

    @classmethod
    def from_profile_fallback(
        cls,
        *,
        map_id: str,
        selected_farms: list[str] | None = None,
        farm_stays_s: dict[str, float] | None = None,
        duration_minutes: int = 60,
    ) -> "RoutineCursor":
        mid = str(map_id or "").strip() or "talking_island"
        row = {
            "id": "profile_fallback",
            "map_id": mid,
            "kind": "battle",
            "duration_minutes": max(1, int(duration_minutes)),
            "selected_farms": list(selected_farms or []),
            "farm_stays_s": dict(farm_stays_s or {}),
        }
        return cls(entries=[row], index=0, started_at=time.monotonic())

    def __len__(self) -> int:
        return len(self.entries)

    def active(self) -> Optional[dict[str, Any]]:
        if not self.entries:
            return None
        return self.entries[self.index % len(self.entries)]

    def mark_arrived(self, *, reset_clock: bool = True) -> None:
        """Record arrival. Return trips keep the row clock that is already running."""
        if reset_clock:
            self.started_at = time.monotonic()
        self.fail_mask.discard(self.index)

    def duration_expired(self) -> bool:
        entry = self.active()
        if entry is None:
            return False
        minutes = int(entry.get("duration_minutes") or 60)
        return (time.monotonic() - float(self.started_at)) >= minutes * 60.0

    def advance(self) -> dict[str, Any] | None:
        if not self.entries:
            return None
        self.index = (self.index + 1) % len(self.entries)
        self.started_at = time.monotonic()
        return self.active()

    def mark_fail(self) -> None:
        if self.entries:
            self.fail_mask.add(self.index % len(self.entries))

    def full_cycle_failed(self) -> bool:
        n = len(self.entries)
        return n > 0 and len(self.fail_mask) >= n

    def reset_fail_mask(self) -> None:
        self.fail_mask.clear()
        self.cycle_start_index = self.index


def goal_for_entry(entry: dict[str, Any], blackboard: Any = None) -> Any:
    """Build a WorldNav Goal from a routine row (pack id + farms/patrol).

    A break row with checked rest areas walks to the first checked area.
    An empty break selection keeps the previous map or patrol goal.
    """
    pack_id = str(entry.get("map_id") or "").strip()
    map_id = pack_ids.pack_id_to_map_id(pack_id)
    if map_id is None:
        raise ValueError(f"unknown routine map pack_id={pack_id!r}")

    kind = str(entry.get("kind") or "battle").strip().lower()
    farms = [str(n) for n in (entry.get("selected_farms") or []) if str(n).strip()]
    rects: list[dict[str, Any]] = []
    if farms and blackboard is not None:
        if kind == "break":
            rects = safe_rects_selected(blackboard, pack_id, farms)
        else:
            rects = farm_rects_selected(blackboard, pack_id, farms)
    if rects:
        r0 = rects[0]
        nx = (int(r0["x0"]) + int(r0["x1"])) // 2
        ny = (int(r0["y0"]) + int(r0["y1"])) // 2
        abs_xy = pack_ids.nav_to_abs(pack_id, nx, ny)
        if abs_xy is not None:
            return api.point_goal(map_id, abs_xy[0], abs_xy[1])

    # Dungeon / no farms: first patrol tile if any.
    patrol: list[tuple[int, int, str]] = []
    if blackboard is not None:
        patrol = patrol_entries(blackboard, pack_id)
    if patrol:
        nx, ny, _label = patrol[0]
        abs_xy = pack_ids.nav_to_abs(pack_id, int(nx), int(ny))
        if abs_xy is not None:
            return api.point_goal(map_id, abs_xy[0], abs_xy[1])

    return api.map_goal(map_id)
