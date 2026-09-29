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


def is_inside_active_farm(blackboard: "Blackboard") -> bool:
    farm = get_active_farm(blackboard.farm_area_index)
    if farm is None:
        return False
    return farm.contains(blackboard.world_origin.x, blackboard.world_origin.y)


def sample_farm_presence(blackboard: "Blackboard") -> None:
    """Once per decide tick: add delta only while inside the active farm."""
    now = time.time()
    inside = is_inside_active_farm(blackboard)
    if blackboard.farm_time_last_sample > 0 and blackboard.farm_time_inside:
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
    blackboard.farm_time_inside = is_inside_active_farm(blackboard)
    from app._04_decision.hunt_area import reset_area_watch

    reset_area_watch(blackboard)


__all__ = [
    "FARM_DURATION_LIMIT",
    "FARM_DURATION_LIMITS",
    "active_farm_duration_limit",
    "is_inside_active_farm",
    "sample_farm_presence",
    "farm_elapsed_seconds",
    "farm_time_exceeded",
    "reset_farm_timer",
]
