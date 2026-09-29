"""Arrival-based hop driver for farm SEARCHING.

This mirrors :mod:`app._04_decision.behaviors.travel` but emits ActionType
``SEARCHING`` and advances hops using memory position (``world_origin``)
instead of a fixed leg tick counter.
"""

from __future__ import annotations

import time

from app._03_world import ActionType
from app._03_world.world_coords import tile_chebyshev
from app._04_decision.behaviors.unstick import (
    SCRATCH_ESCAPED,
    reset_unstick_tries,
    try_movement_unstick,
)
from app._04_decision.farm_area import ARRIVE_TILES
from app._04_decision.nav_config import (
    get_active_farm,
    get_coverage_cell,
    get_terrain_map,
)
from app._04_decision import player_mode as pm


def clear_search_hop(blackboard) -> None:
    blackboard.search_leg_ticks = 0
    blackboard.search_destination = None
    blackboard.search_waypoint = None
    blackboard.search_hop_active = False

    blackboard.search_stuck_tile = None
    blackboard.search_stuck_since_tick = 0
    blackboard.search_stuck_since_time = 0.0
    blackboard.search_unstick_active = False
    reset_unstick_tries(blackboard)


def _near_tile(blackboard, tile: tuple[int, int]) -> bool:
    return (
        tile_chebyshev(
            blackboard.world_origin.x,
            blackboard.world_origin.y,
            tile[0],
            tile[1],
        )
        <= ARRIVE_TILES
    )


def _reset_stuck(blackboard) -> None:
    blackboard.search_stuck_tile = (
        blackboard.world_origin.x,
        blackboard.world_origin.y,
    )
    blackboard.search_stuck_since_tick = blackboard.tick_count
    blackboard.search_stuck_since_time = time.time()


def _is_stuck(blackboard) -> bool:
    cur = (blackboard.world_origin.x, blackboard.world_origin.y)
    if blackboard.search_stuck_tile is not None and blackboard.search_stuck_tile != cur:
        reset_unstick_tries(blackboard)
    if blackboard.search_stuck_tile != cur:
        _reset_stuck(blackboard)
        return False
    if blackboard.search_stuck_since_time <= 0:
        _reset_stuck(blackboard)
        return False
    elapsed = time.time() - blackboard.search_stuck_since_time
    return elapsed >= pm.TRAVEL_UNSTICK_SECONDS


def _emit_search_click(
    blackboard,
    *,
    destination,
    waypoint: tuple[int, int],
    reason: str,
    priority: float,
    mid_act: bool,
) -> None:
    from app.bot_log import event

    blackboard.search_destination = destination
    blackboard.search_waypoint = waypoint
    blackboard.search_hop_active = True
    blackboard.search_unstick_active = False
    blackboard.search_leg_ticks = 0
    if not mid_act:
        event(
            "search",
            "hop start wp=%s reason=%s",
            waypoint,
            reason,
        )
    blackboard.emit(
        ActionType.SEARCHING,
        destination=destination,
        priority=priority,
        reason=reason,
        mid_act=mid_act,
    )


def emit_search_hop(
    blackboard,
    *,
    reason: str,
    priority: float,
    max_leg_ticks: int,
) -> bool:
    """Emit ActionType.SEARCHING for the current tick.

    Returns ``True`` if a click was emitted (mid_act=False), ``False`` if we
    only kept walking (mid_act=True).
    """
    # If SEARCHING was skipped for >1 tick (combat/loot interruption), resume
    # the same hop but reset the age counter.
    if blackboard.last_search_tick > 0 and blackboard.tick_count - blackboard.last_search_tick > 1:
        blackboard.search_leg_ticks = 0

    farm = get_active_farm(blackboard.farm_area_index)
    terrain = get_terrain_map()

    if farm is None or terrain is None:
        clear_search_hop(blackboard)
        return False

    origin = (blackboard.world_origin.x, blackboard.world_origin.y)
    if not farm.contains(*origin):
        # Outside farm: enter-farm travel owns movement; do not invent hops.
        clear_search_hop(blackboard)
        return False

    # Plan a new hop if we have nothing active.
    if blackboard.search_waypoint is None or not blackboard.search_hop_active:
        dest = blackboard.movement_planner.next_leg(blackboard, reason, persist=True)
        if not blackboard.leg_history:
            clear_search_hop(blackboard)
            return False
        last_leg = blackboard.leg_history[-1]
        wp = last_leg.absolute_target
        if wp is None or not last_leg.walkable:
            clear_search_hop(blackboard)
            return False
        _emit_search_click(
            blackboard,
            destination=dest,
            waypoint=wp,
            reason=reason,
            priority=priority,
            mid_act=False,
        )
        blackboard.last_search_tick = blackboard.tick_count
        return True

    # Active hop: wait until memory position reaches the waypoint.
    if _near_tile(blackboard, blackboard.search_waypoint):
        from app.bot_log import event

        # Hop finished: update coverage memory using the reached absolute tile.
        event(
            "search",
            "hop arrive wp=%s",
            blackboard.search_waypoint,
        )
        cell = get_coverage_cell()
        key = (blackboard.search_waypoint[0] // cell, blackboard.search_waypoint[1] // cell)
        blackboard.farm_visit[key] = blackboard.farm_visit.get(key, 0) + 1

        # Clear hop and roll the next click this same tick.
        blackboard.search_destination = None
        blackboard.search_waypoint = None
        blackboard.search_hop_active = False
        blackboard.search_unstick_active = False
        blackboard.search_leg_ticks = 0
        return emit_search_hop(
            blackboard,
            reason=reason,
            priority=priority,
            max_leg_ticks=max_leg_ticks,
        )

    # Not arrived yet -> safety cap based on age.
    blackboard.search_leg_ticks += 1
    if blackboard.search_leg_ticks >= max_leg_ticks:
        from app.bot_log import event

        event("search", "hop replan (leg ticks=%s)", blackboard.search_leg_ticks)
        dest = blackboard.movement_planner.next_leg(blackboard, reason, persist=False)
        if not blackboard.leg_history:
            clear_search_hop(blackboard)
            return False
        last_leg = blackboard.leg_history[-1]
        wp = last_leg.absolute_target
        if wp is None or not last_leg.walkable:
            clear_search_hop(blackboard)
            return False
        _emit_search_click(
            blackboard,
            destination=dest,
            waypoint=wp,
            reason="stuck, jumping elsewhere",
            priority=priority,
            mid_act=False,
        )
        blackboard.last_search_tick = blackboard.tick_count
        return True

    # Soft stuck → 360° nearby clicks, then teleport / talking scroll.
    if try_movement_unstick(
        blackboard,
        stuck=_is_stuck(blackboard),
        action=ActionType.SEARCHING,
        reason="unstick nearby",
        priority=priority,
        on_walk=lambda tile, dest: _emit_search_click(
            blackboard,
            destination=dest,
            waypoint=tile,
            reason="unstick nearby",
            priority=priority,
            mid_act=False,
        ),
    ):
        if blackboard.scratch.pop(SCRATCH_ESCAPED, None):
            blackboard.search_hop_active = False
            blackboard.search_destination = None
            blackboard.search_waypoint = None
            blackboard.search_unstick_active = True
            blackboard.search_leg_ticks = 0
        else:
            blackboard.search_unstick_active = True
        blackboard.last_search_tick = blackboard.tick_count
        return True

    # Keep current destination, no click this tick.
    dest = blackboard.search_destination
    if dest is not None:
        blackboard.last_search_tick = blackboard.tick_count
        blackboard.emit(
            ActionType.SEARCHING,
            destination=dest,
            priority=priority,
            reason=reason,
            mid_act=True,
        )
        return False

    # Stale hop (travel cleared the click dest but left waypoint/active).
    # Replan a fresh hop instead of returning with no intent.
    clear_search_hop(blackboard)
    return emit_search_hop(
        blackboard,
        reason=reason,
        priority=priority,
        max_leg_ticks=max_leg_ticks,
    )


__all__ = [
    "clear_search_hop",
    "emit_search_hop",
]

