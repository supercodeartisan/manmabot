"""Shared TRAVELING hop driver: A* clicks with memory-near-waypoint waits."""
from __future__ import annotations

import time
from typing import TYPE_CHECKING

from app._03_world import ActionType, Position
from app._03_world.world_coords import tile_chebyshev
from app._04_decision.behaviors.unstick import (
    SCRATCH_ESCAPED,
    reset_unstick_tries,
    try_enter_farm_detour,
    try_movement_unstick,
)
from app._04_decision.nav_config import get_terrain_map
from app._04_decision.pathfinding import plan_travel_click, waypoint_to_content
from app._04_decision import player_mode as pm
from app._04_decision import farm_area

if TYPE_CHECKING:  # pragma: no cover
    from app._04_decision.blackboard import Blackboard


def clear_travel(blackboard: "Blackboard") -> None:
    blackboard.nav_goal = None
    blackboard.nav_path.clear()
    blackboard.nav_waypoint = None
    blackboard.travel_destination = None
    blackboard.travel_leg_ticks = 0
    blackboard.last_travel_tick = 0
    blackboard.travel_click_at = 0.0
    blackboard.travel_hop_active = False
    blackboard.travel_stuck_tile = None
    blackboard.travel_stuck_since_tick = 0
    blackboard.travel_stuck_since_time = 0.0
    blackboard.travel_unstick_active = False
    blackboard.travel_soft_unstick_done = False
    reset_unstick_tries(blackboard)


def start_travel(
    blackboard: "Blackboard",
    goal: tuple[int, int],
    *,
    reason: str,
) -> None:
    """Begin (or retarget) guided travel to an absolute tile."""
    blackboard.nav_goal = goal
    blackboard.nav_path.clear()
    blackboard.nav_waypoint = None
    blackboard.travel_destination = None
    blackboard.travel_leg_ticks = 0
    blackboard.last_travel_tick = 0
    from app._04_decision.behaviors.search_hop import clear_search_hop

    clear_search_hop(blackboard)
    blackboard.travel_hop_active = False
    blackboard.travel_click_at = 0.0
    blackboard.travel_stuck_tile = None
    blackboard.travel_stuck_since_tick = 0
    blackboard.travel_stuck_since_time = 0.0
    blackboard.travel_unstick_active = False
    blackboard.travel_soft_unstick_done = False
    reset_unstick_tries(blackboard)
    blackboard.scratch["travel_reason"] = reason


def travel_arrived(blackboard: "Blackboard") -> bool:
    goal = blackboard.nav_goal
    if goal is None:
        return True
    return (
        tile_chebyshev(
            blackboard.world_origin.x,
            blackboard.world_origin.y,
            goal[0],
            goal[1],
        )
        <= farm_area.ARRIVE_TILES
    )


def _near_tile(blackboard: "Blackboard", tile: tuple[int, int]) -> bool:
    return (
        tile_chebyshev(
            blackboard.world_origin.x,
            blackboard.world_origin.y,
            tile[0],
            tile[1],
        )
        <= farm_area.ARRIVE_TILES
    )


def _reset_stuck(blackboard: "Blackboard") -> None:
    blackboard.travel_stuck_tile = (
        blackboard.world_origin.x,
        blackboard.world_origin.y,
    )
    blackboard.travel_stuck_since_tick = blackboard.tick_count
    blackboard.travel_stuck_since_time = time.time()
    blackboard.travel_soft_unstick_done = False


def _stuck_sample(blackboard: "Blackboard") -> tuple[int, float]:
    """Ticks and seconds on the current tile. Resets the clock on a tile change."""
    cur = (blackboard.world_origin.x, blackboard.world_origin.y)
    if blackboard.travel_stuck_tile is not None and blackboard.travel_stuck_tile != cur:
        reset_unstick_tries(blackboard)
    if blackboard.travel_stuck_tile != cur:
        _reset_stuck(blackboard)
        return 0, 0.0
    ticks = blackboard.tick_count - blackboard.travel_stuck_since_tick
    elapsed = time.time() - blackboard.travel_stuck_since_time
    return ticks, elapsed


def _should_reclick(blackboard: "Blackboard") -> bool:
    last = float(blackboard.travel_click_at or 0.0)
    if last <= 0.0:
        return True
    return (time.time() - last) >= pm.TRAVEL_RECLICK_SECONDS


def _mark_travel_unstick(blackboard: "Blackboard") -> None:
    """Keep travel session; drop the blocked hop so the next tick can replan."""
    from app.bot_log import event

    event(
        "travel",
        "unstick purpose=%s wp=%s",
        blackboard.travel_purpose,
        blackboard.nav_waypoint,
    )
    blackboard.travel_hop_active = False
    blackboard.travel_destination = None
    blackboard.nav_waypoint = None
    blackboard.travel_unstick_active = True
    blackboard.nav_path.clear()
    blackboard.last_travel_tick = blackboard.tick_count


def _emit_click(
    blackboard: "Blackboard",
    *,
    content: Position,
    waypoint: tuple[int, int],
    reason: str,
    priority: float,
    mid_act: bool,
) -> None:
    from app.bot_log import event

    blackboard.nav_waypoint = waypoint
    blackboard.travel_destination = content
    blackboard.last_travel_tick = blackboard.tick_count
    blackboard.travel_hop_active = True
    if not mid_act:
        blackboard.travel_click_at = time.time()
        event(
            "travel",
            "hop begin wp=%s purpose=%s reason=%s",
            waypoint,
            blackboard.travel_purpose,
            reason,
        )
    blackboard.emit(
        ActionType.TRAVELING,
        destination=content,
        priority=priority,
        reason=reason,
        mid_act=mid_act,
    )


def emit_travel_hop(
    blackboard: "Blackboard",
    *,
    reason: str,
    priority: float,
) -> bool:
    """Emit TRAVELING for one hop. Returns False if arrived or unreachable.

    Re-clicks about every ``TRAVEL_RECLICK_SECONDS`` from live memory
    position. Same tile ~2.5s → 360° walkable clicks; all radius-2
    tiles failing, 3 standstills in 20s, or low HP → teleport or talking
    scroll. Enter / next-farm with no A* path walks a 5-tile ring first.
    """
    if blackboard.nav_goal is None or travel_arrived(blackboard):
        return False

    # Interrupted by another behavior: replan from live memory position.
    if (
        blackboard.last_travel_tick > 0
        and blackboard.tick_count - blackboard.last_travel_tick > 1
    ):
        blackboard.travel_hop_active = False
        blackboard.travel_destination = None
        blackboard.nav_waypoint = None
        blackboard.travel_unstick_active = False

    terrain = get_terrain_map()
    if terrain is None:
        clear_travel(blackboard)
        return False

    def _walk_unstick(tile: tuple[int, int], dest: Position) -> None:
        blackboard.travel_unstick_active = True
        blackboard.nav_path.clear()
        _emit_click(
            blackboard,
            content=dest,
            waypoint=tile,
            reason="unstick nearby",
            priority=priority,
            mid_act=False,
        )

    def _consume_unstick() -> bool:
        if blackboard.scratch.pop(SCRATCH_ESCAPED, None):
            _mark_travel_unstick(blackboard)
        return True

    # Active hop: wait near waypoint (or unstick tile).
    if blackboard.travel_hop_active and blackboard.nav_waypoint is not None:
        wp = blackboard.nav_waypoint
        if _near_tile(blackboard, wp):
            from app.bot_log import event

            event(
                "travel",
                "hop arrive wp=%s purpose=%s",
                wp,
                blackboard.travel_purpose,
            )
            blackboard.travel_hop_active = False
            blackboard.travel_destination = None
            blackboard.nav_waypoint = None
            blackboard.travel_unstick_active = False
            if travel_arrived(blackboard):
                return False
            # Fall through to plan the next hop this tick.
        else:
            from app._04_decision.mode_control import PURPOSE_ENTER_FARM

            _ticks, elapsed = _stuck_sample(blackboard)
            if try_movement_unstick(
                blackboard,
                stuck=elapsed >= pm.TRAVEL_UNSTICK_SECONDS,
                action=ActionType.TRAVELING,
                reason="unstick nearby",
                priority=priority,
                on_walk=_walk_unstick,
                allow_escape=blackboard.travel_purpose != PURPOSE_ENTER_FARM,
            ):
                return _consume_unstick()
            if _should_reclick(blackboard):
                blackboard.travel_hop_active = False
                blackboard.travel_destination = None
                blackboard.nav_waypoint = None
                blackboard.travel_unstick_active = False
                # Fall through: replan from current origin and click.
            else:
                content = waypoint_to_content(wp, blackboard.world_origin)
                blackboard.travel_destination = content
                blackboard.last_travel_tick = blackboard.tick_count
                blackboard.emit(
                    ActionType.TRAVELING,
                    destination=content,
                    priority=priority,
                    reason=reason,
                    mid_act=True,
                )
                return True

    content, path, wp = plan_travel_click(
        terrain, blackboard.world_origin, blackboard.nav_goal
    )
    if content is None or wp is None or not path:
        from app._04_decision.mode_control import PURPOSE_ENTER_FARM, PURPOSE_NEXT_FARM

        entering = blackboard.travel_purpose in (
            PURPOSE_ENTER_FARM, PURPOSE_NEXT_FARM,
        )
        if entering:
            _stuck_sample(blackboard)
            def _detour_walk(tile: tuple[int, int], dest: Position) -> None:
                blackboard.travel_unstick_active = True
                blackboard.nav_path.clear()
                _emit_click(
                    blackboard,
                    content=dest,
                    waypoint=tile,
                    reason="enter farm, walk around",
                    priority=priority,
                    mid_act=False,
                )

            if try_enter_farm_detour(blackboard, on_walk=_detour_walk):
                return _consume_unstick()
            return False
        _ticks, elapsed = _stuck_sample(blackboard)
        if try_movement_unstick(
            blackboard,
            stuck=elapsed >= pm.TRAVEL_UNSTICK_SECONDS,
            action=ActionType.TRAVELING,
            reason="unstick nearby",
            priority=priority,
            on_walk=_walk_unstick,
        ):
            return _consume_unstick()
        return False

    blackboard.nav_path = list(path)
    _emit_click(
        blackboard,
        content=content,
        waypoint=wp,
        reason=reason,
        priority=priority,
        mid_act=False,
    )
    return True


__all__ = [
    "clear_travel",
    "start_travel",
    "travel_arrived",
    "emit_travel_hop",
]
