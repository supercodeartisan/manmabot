"""Accumulate time spent inside the active farm rect (not wall-clock session)."""
from __future__ import annotations

import time
from typing import TYPE_CHECKING

from app._04_decision.nav_config import get_active_farm

if TYPE_CHECKING:  # pragma: no cover
    from app._04_decision.blackboard import Blackboard

# Seconds of in-farm presence before rotating to the next farm area.
FARM_DURATION_LIMIT = 600.0
# Per-farm stay seconds aligned with ``get_farm_areas()`` order. Empty = use
# ``FARM_DURATION_LIMIT`` for every area.
FARM_DURATION_LIMITS: list[float] = []


def active_farm_duration_limit(blackboard: "Blackboard") -> float:
    """Stay seconds for the farm currently on the tour."""
    idx = int(getattr(blackboard, "farm_area_index", 0) or 0)
    if 0 <= idx < len(FARM_DURATION_LIMITS):
        limit = float(FARM_DURATION_LIMITS[idx])
        if limit > 0:
            return limit
    return float(FARM_DURATION_LIMIT)


# ``pack:farm_name`` of the stay currently being timed. Arrival at the
# walk goal (the rect center) must not clear a stay already started.
SCRATCH_FARM_STAY_KEY = "farm_stay_key"


def is_inside_active_farm(blackboard: "Blackboard") -> bool:
    farm = get_active_farm(blackboard.farm_area_index)
    if farm is None:
        return False
    return farm.contains(blackboard.world_origin.x, blackboard.world_origin.y)


def _live_map_matches_pack(blackboard: "Blackboard", pack_id: str) -> bool:
    from app._04_decision.live_map_pack import SCRATCH_LIVE_MAP_ID
    from app._04_decision.world_nav.pack_ids import pack_id_to_map_id

    want = pack_id_to_map_id(pack_id)
    if want is None:
        return False
    live = blackboard.scratch.get(SCRATCH_LIVE_MAP_ID)
    try:
        return live is not None and int(live) == int(want)
    except (TypeError, ValueError):
        return False


def trip_destination_farm(blackboard: "Blackboard"):
    """Rectangle the current walk is heading to, in nav tiles.

    World nav finishes at the center of this rect. The stay clock has to see
    the whole rect as soon as the character is on that map, before arrival.
    Returns None when there is no farm trip or the live map is still elsewhere.
    """
    from app._04_decision.farm_area import farm_rect_from_mapping
    from app._04_decision.farm_tour import RETURN_FARM_REASONS, return_farm_index

    scratch = blackboard.scratch
    session = scratch.get("world_nav_session")
    purpose = str(getattr(blackboard, "travel_purpose", "") or "")
    # ``world_nav`` alone is not a trip. After the session ends that purpose
    # used to point the clock at the first checked area.
    on_trip = session is not None or purpose in ("next_farm", "enter_farm")
    if not on_trip:
        return None
    cursor = scratch.get("routine_cursor")
    entry = cursor.active() if cursor is not None and hasattr(cursor, "active") else None
    if not isinstance(entry, dict):
        return None
    if str(entry.get("kind") or "battle").strip().lower() == "break":
        return None
    pack_id = str(entry.get("map_id") or "").strip()
    if not pack_id or not _live_map_matches_pack(blackboard, pack_id):
        return None
    names = [str(n) for n in (entry.get("selected_farms") or []) if str(n).strip()]
    if not names:
        return None
    from app._04_decision.world_nav.overlays import farm_rects_selected

    rects = farm_rects_selected(blackboard, pack_id, names)
    if not rects:
        return None
    reason = str(getattr(session, "reason", "") or "")
    if reason in RETURN_FARM_REASONS:
        index = return_farm_index(blackboard, len(rects))
    elif reason == "farm_area" or purpose == "next_farm":
        try:
            index = int(getattr(blackboard, "farm_area_index", 0) or 0)
        except (TypeError, ValueError):
            index = 0
    else:
        index = 0
    if index < 0 or index >= len(rects):
        index = 0
    try:
        return farm_rect_from_mapping(rects[index], index=index)
    except (KeyError, TypeError, ValueError):
        return None


def clock_farm(blackboard: "Blackboard"):
    """Farm the stay clock should follow. The trip target wins over the loaded slot."""
    dest = trip_destination_farm(blackboard)
    if dest is not None:
        return dest
    return get_active_farm(getattr(blackboard, "farm_area_index", 0))


def inside_farm_stay(blackboard: "Blackboard") -> bool:
    """True when the live nav tile is inside the farm the stay clock is timing."""
    farm = clock_farm(blackboard)
    if farm is None:
        return False
    return farm.contains(int(blackboard.world_origin.x), int(blackboard.world_origin.y))


def farm_stay_key(blackboard: "Blackboard") -> str:
    farm = clock_farm(blackboard)
    name = "" if farm is None else str(getattr(farm, "name", "") or "")
    pack = ""
    cursor = blackboard.scratch.get("routine_cursor")
    entry = cursor.active() if cursor is not None and hasattr(cursor, "active") else None
    if isinstance(entry, dict):
        pack = str(entry.get("map_id") or "")
    return f"{pack}:{name}"


def sample_farm_presence(blackboard: "Blackboard") -> None:
    """Once per decide tick: add delta only while inside the stay rectangle.

    The stay starts on the first sample inside that rectangle, including the
    walk from the edge to the center. Leaving and re-entering continues the
    same elapsed time. A different farm zeroes the previous stay.
    """
    now = time.time()
    inside = inside_farm_stay(blackboard)
    key = farm_stay_key(blackboard) if inside else ""
    switched = bool(
        inside and key and str(blackboard.scratch.get(SCRATCH_FARM_STAY_KEY) or "") != key
    )
    if switched:
        blackboard.farm_elapsed_seconds = 0.0
        blackboard.scratch[SCRATCH_FARM_STAY_KEY] = key
    fresh = inside and not blackboard.farm_time_inside and (
        switched or float(blackboard.farm_elapsed_seconds or 0.0) <= 0.0
    )
    if fresh:
        from app.bot_log import get_logger

        farm = clock_farm(blackboard)
        get_logger("nav").info(
            "farm stay start name=%s index=%s at (%s,%s)",
            getattr(farm, "name", "-"),
            getattr(blackboard, "farm_area_index", "-"),
            blackboard.world_origin.x,
            blackboard.world_origin.y,
        )
    if (
        not switched
        and blackboard.farm_time_last_sample > 0
        and blackboard.farm_time_inside
    ):
        blackboard.farm_elapsed_seconds += now - blackboard.farm_time_last_sample
    blackboard.farm_time_last_sample = now
    blackboard.farm_time_inside = inside


def farm_elapsed_seconds(blackboard: "Blackboard") -> float:
    """Committed in-farm seconds plus any open inside segment."""
    total = blackboard.farm_elapsed_seconds
    if blackboard.farm_time_inside and blackboard.farm_time_last_sample > 0:
        total += time.time() - blackboard.farm_time_last_sample
    return total


def farm_time_exceeded(blackboard: "Blackboard") -> bool:
    return farm_elapsed_seconds(blackboard) >= active_farm_duration_limit(blackboard)


def reset_farm_timer(blackboard: "Blackboard") -> None:
    """Clear accumulated in-farm time (call when starting a new farm stay)."""
    blackboard.farm_elapsed_seconds = 0.0
    blackboard.farm_time_last_sample = time.time()
    blackboard.farm_time_inside = inside_farm_stay(blackboard)
    blackboard.scratch[SCRATCH_FARM_STAY_KEY] = farm_stay_key(blackboard)
    from app._04_decision.hunt_area import reset_area_watch

    reset_area_watch(blackboard)


__all__ = [
    "FARM_DURATION_LIMIT",
    "FARM_DURATION_LIMITS",
    "active_farm_duration_limit",
    "SCRATCH_FARM_STAY_KEY",
    "is_inside_active_farm",
    "trip_destination_farm",
    "clock_farm",
    "inside_farm_stay",
    "farm_stay_key",
    "sample_farm_presence",
    "farm_elapsed_seconds",
    "farm_time_exceeded",
    "reset_farm_timer",
]
