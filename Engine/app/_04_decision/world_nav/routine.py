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

    def _zero_clock(self) -> None:
        """Drop the stay. Sampling starts it again inside the hunt zone."""
        self.elapsed_s = 0.0
        self.running_since = 0.0

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
        # Stay at zero until the character is inside this row's hunt zone.
        return cls(entries=rows, index=0)

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
        """Record arrival.

        The row clock is not started or cleared here. ``reset_clock`` remains
        so existing callers keep working, and it is ignored: reaching the
        center must not erase time already counted from the zone edge.
        ``advance`` zeros a new row. Stop drops the cursor.
        """
        del reset_clock
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
        self._zero_clock()
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


def battle_destination_nav_rect(
    entry: dict[str, Any],
    blackboard: Any = None,
    *,
    reason: str = "",
) -> tuple[str, int, Any] | None:
    """Nav-tile hunt rect the field walk is heading to.

    Break rows are not included: those still walk to the rest-area center.
    ``None`` when this battle row has no checked farm rect. The planner
    still aims at the rect center; arrival is the border, not that point.
    """
    from app._04_decision.farm_area import farm_rect_from_mapping

    pack_id = str(entry.get("map_id") or "").strip()
    map_id = pack_ids.pack_id_to_map_id(pack_id)
    if map_id is None or blackboard is None:
        return None
    kind = str(entry.get("kind") or "battle").strip().lower()
    if kind == "break":
        return None
    farms = [str(n) for n in (entry.get("selected_farms") or []) if str(n).strip()]
    if not farms:
        return None
    rects = farm_rects_selected(blackboard, pack_id, farms)
    if not rects:
        return None
    index = 0
    from app._04_decision.farm_tour import RETURN_FARM_REASONS, return_farm_index

    if str(reason or "") in RETURN_FARM_REASONS:
        index = return_farm_index(blackboard, len(rects))
    elif str(reason or "") == "farm_area":
        try:
            index = int(getattr(blackboard, "farm_area_index", 0) or 0)
        except (TypeError, ValueError):
            index = 0
        if index < 0 or index >= len(rects):
            index = 0
    try:
        rect = farm_rect_from_mapping(rects[index], index=index)
    except (KeyError, TypeError, ValueError):
        return None
    return pack_id, int(map_id), rect


def pose_inside_battle_rect(
    pose: Any,
    entry: dict[str, Any],
    blackboard: Any = None,
    *,
    reason: str = "",
) -> bool:
    """True when ``pose`` is on this row's map and inside its hunt rect."""
    chosen = battle_destination_nav_rect(entry, blackboard, reason=reason)
    if chosen is None or pose is None:
        return False
    pack_id, map_id, rect = chosen
    try:
        if int(pose.map_id) != int(map_id):
            return False
        px, py = int(pose.x), int(pose.y)
    except (TypeError, ValueError, AttributeError):
        return False
    nav = pack_ids.abs_to_nav(pack_id, px, py)
    if nav is None:
        return False
    return bool(rect.contains(int(nav[0]), int(nav[1])))


def pose_at_dungeon_entrance(
    pose: Any,
    entry: dict[str, Any],
    blackboard: Any = None,
) -> bool:
    """True once the live map is the dungeon world-nav destination.

    A deeper floor's world nav ends on the complex entrance map. An
    entrance-floor row ends when the live map is that floor. Field rows
    are not dungeons.
    """
    from app._04_decision.dungeon_floor_route import (
        needs_floor_route,
        world_nav_entrance_map_id,
    )
    from .overlays import is_dungeon_pack

    if pose is None or blackboard is None:
        return False
    pack_id = str(entry.get("map_id") or "").strip()
    if not pack_id or not is_dungeon_pack(blackboard, pack_id):
        return False
    try:
        live_map = int(pose.map_id)
    except (TypeError, ValueError, AttributeError):
        return False
    if needs_floor_route(pack_id):
        entrance = world_nav_entrance_map_id(pack_id)
        return entrance is not None and live_map == int(entrance)
    home = pack_ids.pack_id_to_map_id(pack_id)
    return home is not None and live_map == int(home)


def pose_hunt_arrival(
    pose: Any,
    entry: dict[str, Any],
    blackboard: Any = None,
    *,
    reason: str = "",
) -> bool:
    """Field border or dungeon entrance. Break rows never arrive this way."""
    if str(entry.get("kind") or "battle").strip().lower() == "break":
        return False
    if battle_destination_nav_rect(entry, blackboard, reason=reason) is not None:
        return pose_inside_battle_rect(
            pose, entry, blackboard, reason=reason
        )
    return pose_at_dungeon_entrance(pose, entry, blackboard)


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


def routine_hunt_zone_inside(blackboard: Any) -> bool:
    """True when this battle row should be counting.

    A field row counts inside any selected farm rectangle on its map.
    A dungeon row counts on the hunt floor. A row with no rectangles counts
    once the live map is that pack. Break rows are not a hunt zone.
    """
    cursor = _routine_cursor(blackboard)
    entry = cursor.active() if cursor is not None else None
    if not isinstance(entry, dict):
        return False
    if str(entry.get("kind") or "battle").strip().lower() == "break":
        return False
    pack_id = str(entry.get("map_id") or "").strip()
    if not pack_id:
        return False
    if _routine_row_is_dungeon(blackboard):
        from app._03_world.space.map_pack import get_active_map_pack
        from app._04_decision.dungeon_floor_route import (
            arrived_on_hunt_floor,
            needs_floor_route,
        )

        live = get_active_map_pack()
        live_id = "" if live is None else str(live.id)
        if needs_floor_route(pack_id):
            return bool(arrived_on_hunt_floor(live_id, pack_id))
        return live_id == pack_id

    from app._04_decision.farm_time import _live_map_matches_pack

    if not _live_map_matches_pack(blackboard, pack_id):
        return False
    names = [str(n) for n in (entry.get("selected_farms") or []) if str(n).strip()]
    if not names:
        return True
    from app._04_decision.farm_area import farm_rect_from_mapping
    from app._04_decision.world_nav.overlays import farm_rects_selected

    rects = farm_rects_selected(blackboard, pack_id, names)
    if not rects:
        return False
    origin = getattr(blackboard, "world_origin", None)
    if origin is None:
        return False
    try:
        x = int(origin.x)
        y = int(origin.y)
    except (TypeError, ValueError, AttributeError):
        return False
    for index, raw in enumerate(rects):
        if not isinstance(raw, dict):
            continue
        try:
            farm = farm_rect_from_mapping(raw, index=index)
        except (KeyError, TypeError, ValueError):
            continue
        if farm.contains(x, y):
            return True
    return False


def sample_routine_zone_clock(blackboard: Any) -> None:
    """Open the row clock only while the project is deciding inside the zone.

    Leaving the zone commits the seconds and holds them. The next entry
    continues. A dungeon retreat hold stays frozen until the hunt floor
    releases it. Pause never reaches this sampler.
    """
    cursor = _routine_cursor(blackboard)
    if cursor is None:
        return
    scratch = getattr(blackboard, "scratch", None)
    if isinstance(scratch, dict) and scratch.get(ROUTINE_CLOCK_HELD):
        return
    entry = cursor.active()
    kind = "battle"
    if isinstance(entry, dict):
        kind = str(entry.get("kind") or "battle").strip().lower()
    counting = kind == "break" or routine_hunt_zone_inside(blackboard)
    if not counting:
        cursor.freeze()
        return
    fresh = (not cursor.ticking()) and cursor.elapsed() <= 0.0
    cursor.resume()
    if not fresh:
        return
    from app.bot_log import get_logger

    origin = getattr(blackboard, "world_origin", None)
    get_logger("nav").info(
        "routine clock start map=%s kind=%s at (%s,%s)",
        None if not isinstance(entry, dict) else entry.get("map_id"),
        kind,
        getattr(origin, "x", "-"),
        getattr(origin, "y", "-"),
    )
