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
    # Committed stay seconds. The open segment is ``running_since`` .. now.
    # ``running_since`` is 0 while the bot is paused, so pause time is not counted.
    elapsed_s: float = 0.0
    running_since: float = 0.0
    fail_mask: set[int] = field(default_factory=set)
    cycle_start_index: int = 0

    def _start_clock(self) -> None:
        self.elapsed_s = 0.0
        self.running_since = time.monotonic()

    def elapsed(self, now: float | None = None) -> float:
        total = float(self.elapsed_s)
        since = float(self.running_since)
        if since > 0.0:
            total += (time.monotonic() if now is None else now) - since
        return total if total > 0.0 else 0.0

    def ticking(self) -> bool:
        return float(self.running_since) > 0.0

    def freeze(self, now: float | None = None) -> None:
        """Commit the open segment and stop. A second call does not add time."""
        since = float(self.running_since)
        if since <= 0.0:
            return
        now_m = time.monotonic() if now is None else now
        self.elapsed_s = float(self.elapsed_s) + (now_m - since)
        self.running_since = 0.0

    def resume(self, now: float | None = None) -> None:
        """Open a new segment. Seconds already committed stay as they are."""
        if float(self.running_since) > 0.0:
            return
        self.running_since = time.monotonic() if now is None else now

    @classmethod
    def from_entries(cls, entries: list[dict[str, Any]] | None) -> "RoutineCursor":
        """Build from already-normalized routine rows (session inject path)."""
        rows = [dict(e) for e in (entries or []) if isinstance(e, dict)]
        cursor = cls(entries=rows, index=0)
        cursor._start_clock()
        return cursor

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
        return cls.from_entries([row])

    def __len__(self) -> int:
        return len(self.entries)

    def active(self) -> Optional[dict[str, Any]]:
        if not self.entries:
            return None
        return self.entries[self.index % len(self.entries)]

    def mark_arrived(self, *, reset_clock: bool = True) -> None:
        """Record arrival. Return trips keep the row clock that is already running."""
        if reset_clock:
            self._start_clock()
        self.fail_mask.discard(self.index)

    def duration_expired(self) -> bool:
        entry = self.active()
        if entry is None:
            return False
        minutes = int(entry.get("duration_minutes") or 60)
        return self.elapsed() >= minutes * 60.0

    def advance(self) -> dict[str, Any] | None:
        if not self.entries:
            return None
        self.index = (self.index + 1) % len(self.entries)
        self._start_clock()
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


def goal_for_entry(
    entry: dict[str, Any],
    blackboard: Any = None,
    *,
    reason: str = "",
) -> Any:
    """Build a WorldNav Goal from a routine row (pack id + farms/patrol).

    A break row with checked rest areas walks to the first checked area.
    A return onto the same hunt row walks to the farm the character left.
    ``farm_area`` walks to ``farm_area_index`` (the tour slot just selected).
    A new row walks to the first checked farm. An empty break selection
    keeps the previous map or patrol goal.
    """
    pack_id = str(entry.get("map_id") or "").strip()
    map_id = pack_ids.pack_id_to_map_id(pack_id)
    if map_id is None:
        raise ValueError(f"unknown routine map pack_id={pack_id!r}")

    # Deeper dungeon floors: world nav stops at the complex entrance.
    # Floor-to-floor cells are planned later and walked by existing travel.
    from app._04_decision.dungeon_floor_route import world_nav_entrance_map_id

    entrance_map = world_nav_entrance_map_id(pack_id)
    if entrance_map is not None and int(entrance_map) != int(map_id):
        return api.map_goal(int(entrance_map))

    kind = str(entry.get("kind") or "battle").strip().lower()
    farms = [str(n) for n in (entry.get("selected_farms") or []) if str(n).strip()]
    rects: list[dict[str, Any]] = []
    if farms and blackboard is not None:
        if kind == "break":
            rects = safe_rects_selected(blackboard, pack_id, farms)
        else:
            rects = farm_rects_selected(blackboard, pack_id, farms)
    if rects:
        index = 0
        returning = False
        if blackboard is not None and kind != "break":
            from app._04_decision.farm_tour import RETURN_FARM_REASONS, return_farm_index

            returning = str(reason or "") in RETURN_FARM_REASONS
            if returning:
                index = return_farm_index(blackboard, len(rects))
            elif str(reason or "") == "farm_area":
                try:
                    index = int(getattr(blackboard, "farm_area_index", 0) or 0)
                except (TypeError, ValueError):
                    index = 0
                if index < 0 or index >= len(rects):
                    index = 0
        chosen = rects[index]
        nx = (int(chosen["x0"]) + int(chosen["x1"])) // 2
        ny = (int(chosen["y0"]) + int(chosen["y1"])) // 2
        abs_xy = pack_ids.nav_to_abs(pack_id, nx, ny)
        if abs_xy is not None:
            if returning:
                from app.bot_log import get_logger

                get_logger("nav").info(
                    "return farm index=%s of %s reason=%s",
                    index,
                    len(rects),
                    reason or "-",
                )
            elif str(reason or "") == "farm_area":
                from app.bot_log import get_logger

                get_logger("nav").info(
                    "field world nav goal index=%s of %s pack=%s reason=%s",
                    index,
                    len(rects),
                    pack_id,
                    reason or "-",
                )
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


# Dungeon row clock paused for a retreat. World-tree time is not counted.
ROUTINE_CLOCK_HELD = "routine_clock_held"
# Return reason kept until the hunt floor is reached. Deeper floors arrive later.
ROUTINE_RETURN_REASON = "routine_return_reason"


def _routine_cursor(blackboard: Any) -> RoutineCursor | None:
    scratch = getattr(blackboard, "scratch", None)
    if not isinstance(scratch, dict):
        return None
    from app._04_decision.world_nav.hooks import SCRATCH_ROUTINE

    cursor = scratch.get(SCRATCH_ROUTINE)
    return cursor if isinstance(cursor, RoutineCursor) else None


def _routine_row_is_dungeon(blackboard: Any) -> bool:
    cursor = _routine_cursor(blackboard)
    entry = cursor.active() if cursor is not None else None
    if not isinstance(entry, dict):
        return False
    if str(entry.get("kind") or "battle").strip().lower() == "break":
        return False
    pack_id = str(entry.get("map_id") or "").strip()
    if not pack_id:
        return False
    from app._04_decision.world_nav.overlays import is_dungeon_pack

    return bool(is_dungeon_pack(blackboard, pack_id))


def hold_dungeon_routine_clock(blackboard: Any) -> None:
    """Pause a dungeon routine clock when a retreat starts.

    A revive retreat holds the same clock. Returning to the hunt floor
    resumes the saved seconds.
    """
    scratch = getattr(blackboard, "scratch", None)
    if not isinstance(scratch, dict):
        return
    if scratch.get(ROUTINE_CLOCK_HELD):
        return
    if not _routine_row_is_dungeon(blackboard):
        return
    cursor = _routine_cursor(blackboard)
    if cursor is None:
        return
    cursor.freeze()
    scratch[ROUTINE_CLOCK_HELD] = True
    from app.bot_log import get_logger

    get_logger("nav").info(
        "routine clock pause elapsed=%.0fs",
        cursor.elapsed(),
    )


def release_dungeon_routine_clock(blackboard: Any) -> bool:
    """Resume a paused dungeon routine clock. False when nothing was held."""
    scratch = getattr(blackboard, "scratch", None)
    if not isinstance(scratch, dict) or not scratch.pop(ROUTINE_CLOCK_HELD, None):
        return False
    cursor = _routine_cursor(blackboard)
    if cursor is None:
        return False
    cursor.resume()
    from app.bot_log import get_logger

    get_logger("nav").info(
        "routine clock resume elapsed=%.0fs",
        cursor.elapsed(),
    )
    return True
